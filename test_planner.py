"""
test_planner.py — Run the BriefingPlanner agent end-to-end against real data.

Aggregates candidates from all sources (mocked email triage for now since the
Gmail MCP only runs inside Cowork; uses real RSS/API data for Lenny + YouTube +
Bay Club), constructs the planner input JSON, calls Claude with the planner
system prompt, and prints the resulting playlist.

Does NOT generate audio yet. Phase 3 Day 8 = prompt-tested-against-real-data
only. Day 9+ wires the output into the existing TTS pipeline.

Run: python test_planner.py
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

try:
    import feedparser
    import requests
    from anthropic import Anthropic
except ImportError as exc:
    print(f"ERROR: missing dependency — {exc.name}")
    print("Run: pip install feedparser requests anthropic")
    sys.exit(1)


# --- Configuration -----------------------------------------------------------

# Pull these from .env (already set up in earlier steps)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

LENNY_FEED = "https://api.substack.com/feed/podcast/10845.rss"
YT_CHANNELS = [
    ("DeepLearning.AI", "UCcIXc5mJsHVYTZR1maL5l9w"),
    ("Agentic AI Institute (Mahesh Yadav)", "UCPnDl-FpDXdPWKVRRV5V7og"),
]
BAYCLUB_API = (
    "https://bayclubs-classes-czdrbdfgdef2h5ef.westus-01.azurewebsites.net"
    "/api/getClasses"
)
BAYCLUB_FILTER = {
    "Group Power", "ChoreoBarre", "Zumba", "Bollywood Jam",
    "Balance Sculpt", "Mat Pilates", "Rhythm Ride",
}

# Test parameters — adjust these to try different briefings
TIME_BUDGET_MINUTES = 60
MODE = "default"  # default | catchup | learning | executive

# Load the planner system prompt
PLANNER_PROMPT_PATH = Path(__file__).parent / "prompts" / "planner.md"
PLANNER_SYSTEM_PROMPT = PLANNER_PROMPT_PATH.read_text()


# --- Helpers -----------------------------------------------------------------

def strip_html(text: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def minutes_to_time(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h if h <= 12 else h - 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {period}"


# --- Source fetchers ---------------------------------------------------------

# State file paths for multi-day Lenny continuation + Watch Later
STATE_DIR = Path(__file__).parent / "state"
STATE_DIR.mkdir(exist_ok=True)
LENNY_STATE = STATE_DIR / "lenny.json"
WATCH_LATER_STATE = STATE_DIR / "watch_later.json"


def load_lenny_state() -> dict:
    """{episode_id, listening_position_seconds, last_updated} or empty dict."""
    if not LENNY_STATE.exists():
        return {}
    try:
        return json.loads(LENNY_STATE.read_text())
    except json.JSONDecodeError:
        return {}


def fetch_lenny() -> Optional[dict]:
    """Latest Lenny's Podcast episode + any in-progress listening state."""
    feed = feedparser.parse(LENNY_FEED)
    if not feed.entries:
        return None
    e = feed.entries[0]
    audio_url = None
    for link in e.get("links", []):
        if link.get("rel") == "enclosure" and "audio" in link.get("type", ""):
            audio_url = link.get("href")
            break
    duration_raw = e.get("itunes_duration", "")
    duration_seconds = 0
    if duration_raw:
        if ":" in duration_raw:
            parts = list(map(int, duration_raw.split(":")))
            if len(parts) == 3:
                duration_seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
            elif len(parts) == 2:
                duration_seconds = parts[0] * 60 + parts[1]
        else:
            try:
                duration_seconds = int(duration_raw)
            except ValueError:
                pass

    # GUID — use feed's permalink or pubDate as the episode identifier
    episode_id = e.get("id") or e.get("guid") or e.get("published", "")

    # Multi-day continuation: read state, attach listening_position_seconds
    state = load_lenny_state()
    if state.get("episode_id") == episode_id:
        listening_position = state.get("listening_position_seconds", 0)
    else:
        listening_position = 0  # New episode; start from beginning

    return {
        "title": e.title,
        "episode_id": episode_id,
        "published": e.get("published", ""),
        "duration_seconds": duration_seconds,
        "listening_position_seconds": listening_position,
        "url": audio_url,
        "description": strip_html(
            e.get("summary", e.get("description", ""))
        )[:1000],
    }


def fetch_youtube() -> list:
    """Latest 1 full (non-Shorts) episode from each tracked channel."""
    results = []
    for name, channel_id in YT_CHANNELS:
        feed_url = (
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        )
        feed = feedparser.parse(feed_url)
        for video in feed.entries:
            url = video.get("link", "")
            if "/shorts/" in url:
                continue
            description = ""
            if hasattr(video, "media_description"):
                description = video.media_description
            elif video.get("summary"):
                description = video.summary
            results.append({
                "channel": name,
                "title": video.title,
                "published": video.get("published", ""),
                "url": url,
                "description": strip_html(description)[:800],
            })
            break  # only take the first non-Shorts per channel
    return results


def fetch_bayclub(days_ahead: int = 2) -> list:
    """Today + tomorrow (or N days ahead) Bay Club matches."""
    matches = []
    today = datetime.now().date()
    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        date_str = d.strftime("%Y-%m-%d")
        try:
            resp = requests.get(
                BAYCLUB_API,
                params={"club": "pleasanton",
                        "dateFrom": date_str, "dateTo": date_str},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"WARNING: Bay Club fetch failed for {date_str}: {e}")
            continue
        for item in resp.json().get("items", []):
            if item.get("status") != "active":
                continue
            title = item.get("title", "")
            title_lower = title.lower()
            if not any(t.lower() in title_lower for t in BAYCLUB_FILTER):
                continue
            matches.append({
                "title": title.strip(),
                "day_date_label": d.strftime("%a %b %d"),
                "start_time": minutes_to_time(item["timeFromInMinutes"]),
                "end_time": minutes_to_time(item["timeToInMinutes"]),
                "instructor": (item.get("instructor", "") or "").strip() or "TBD",
                "location": (item.get("location", "") or "").strip() or "TBD",
            })
    return matches


def mock_emails() -> list:
    """
    Mock email candidates for testing the planner.

    The real Gmail triage runs inside Cowork (which has the MCP connection)
    and feeds JSON like this to the planner. For local testing, we use a
    small representative set that matches the kinds of emails the classifier
    would actually surface.
    """
    return [
        {
            "bucket": "summarize",
            "sender": "thebatch@deeplearning.ai",
            "subject": ("China Thwarts Meta's Agentic Ambition, U.S. Evaluates "
                        "Upcoming Models, AI Diagnoses Mammograms"),
            "snippet": ("This week in The Batch: China restricts Meta's "
                        "agentic AI rollout. The U.S. evaluates frontier "
                        "model capabilities ahead of release. AI demonstrates "
                        "diagnostic accuracy on mammograms competitive with "
                        "radiologists."),
            "date": "2026-05-15",
        },
        {
            "bucket": "summarize",
            "sender": "peteryang+podcast@substack.com",
            "subject": "Inside How Anthropic Is Building the Next Claude | Alex Albert",
            "snippet": ("Peter Yang interviews Alex Albert about how "
                        "Anthropic's research team picks which model "
                        "capabilities to invest in and how they train "
                        "Claude's character."),
            "date": "2026-05-17",
        },
    ]


# --- Build planner input -----------------------------------------------------

now = datetime.now()
candidates = {
    "emails": mock_emails(),
    "lenny_podcast": fetch_lenny(),
    "youtube": fetch_youtube(),
    "bay_club_classes": fetch_bayclub(),
}

planner_input = {
    "time_budget_minutes": TIME_BUDGET_MINUTES,
    "mode": MODE,
    "current_date": now.strftime("%Y-%m-%d"),
    "current_day_of_week": now.strftime("%A"),
    "candidates": candidates,
}

print("=" * 60)
print(f"Planner input ({TIME_BUDGET_MINUTES}-min budget, mode={MODE!r}):")
print("=" * 60)
print(f"  Emails:           {len(candidates['emails'])} candidate(s)")
print(f"  Lenny podcast:    "
      f"{'present' if candidates['lenny_podcast'] else 'missing'}")
print(f"  YouTube videos:   {len(candidates['youtube'])} candidate(s)")
print(f"  Bay Club classes: {len(candidates['bay_club_classes'])} candidate(s)")
print()

# --- Call Claude -------------------------------------------------------------

print("Calling Claude (model: claude-sonnet-4-5)...")
client = Anthropic(api_key=ANTHROPIC_API_KEY)

resp = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    system=PLANNER_SYSTEM_PROMPT,
    messages=[
        {
            "role": "user",
            "content": (
                "Here is today's input. Return ONLY the JSON object as "
                "described in the system prompt, no other text.\n\n"
                f"```json\n{json.dumps(planner_input, indent=2)}\n```"
            ),
        }
    ],
)

raw = resp.content[0].text.strip()

# Strip ```json ... ``` fences if present
if raw.startswith("```"):
    raw = raw.split("```", 2)[1]
    if raw.startswith("json"):
        raw = raw[4:].strip()
    if raw.endswith("```"):
        raw = raw[:-3].strip()

try:
    playlist = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"ERROR: Couldn't parse planner output as JSON: {e}")
    print("Raw response:")
    print(raw)
    sys.exit(1)

# --- Pretty-print the playlist ----------------------------------------------

print()
print("=" * 60)
print("Planner output:")
print("=" * 60)
print(f"Rationale: {playlist.get('rationale', '(none)')}")
print(f"Estimated total: "
      f"{playlist.get('estimated_total_seconds', '?')} seconds")
print(f"Segments: {len(playlist.get('segments', []))}")
print()

for i, seg in enumerate(playlist.get("segments", []), 1):
    seg_type = seg.get("type", "tts")
    label = seg.get("label", "(no label)")
    if seg_type == "audio":
        url = seg.get("audio_url", "(no url)")
        start = seg.get("start_seconds", 0)
        duration = seg.get("duration_seconds", 0)
        print(f"[{i}] [AUDIO] {label}")
        print(f"    Source URL:  {url[:80]}...")
        print(f"    Start at:    {start}s ({start // 60}m {start % 60}s)")
        print(f"    Duration:    {duration}s "
              f"({duration // 60}m {duration % 60}s)")
    else:
        print(f"[{i}] [TTS]   {label}")
        print(f"    {seg.get('text', '(no text)')}")
    print()

# Show what would be added to the Watch Later list
watch_later = playlist.get("watch_later_urls", [])
if watch_later:
    print(f"Watch Later URLs to save: {len(watch_later)}")
    for w in watch_later:
        print(f"  - {w.get('channel', '?')}: {w.get('title', '?')}")
        print(f"    {w.get('url', '?')}")
    print()

print("Next: feed TTS segments to ElevenLabs, download + slice audio segments,")
print("      stitch all with pydub, push to RSS feed, update state files.")
