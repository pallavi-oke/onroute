"""
generate_briefing.py — End-to-end OnRoute briefing generator.

Pipeline (Phase 3 Day 8):
  1. Aggregate candidates from all sources (mock emails for now, real for the rest).
  2. Call BriefingPlanner (Claude) to compose the playlist.
  3. For each TTS segment: call ElevenLabs, save MP3 chunk.
  4. For each audio segment: download source MP3 (cached), slice with pydub.
  5. Stitch all segments with 400ms silence between, export final briefing.
  6. Update state files: state/lenny.json (listening position),
     state/watch_later.json (YouTube URLs to come back to).
  7. Auto-play the result so we can hear it.

Run: python generate_briefing.py

Cost note: ElevenLabs charges per character. A 10-min TTS briefing is roughly
~$1-3. Lenny audio download is free but ~90 MB per episode (cached after first
download).
"""

import json
import os
import re
import subprocess
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
    from elevenlabs.client import ElevenLabs
    from pydub import AudioSegment
except ImportError as exc:
    print(f"ERROR: missing dependency — {exc.name}")
    sys.exit(1)


# --- Config ------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

if not all([ANTHROPIC_API_KEY, ELEVENLABS_API_KEY, VOICE_ID]):
    print("ERROR: Missing one or more required credentials in .env")
    sys.exit(1)

TIME_BUDGET_MINUTES = 60
MODE = "default"

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

ROOT = Path(__file__).parent
PROMPTS = ROOT / "prompts"
STATE_DIR = ROOT / "state"
DOWNLOADS = ROOT / "downloads"
OUTPUT = ROOT / "output"
for d in (STATE_DIR, DOWNLOADS, OUTPUT):
    d.mkdir(exist_ok=True)

LENNY_STATE = STATE_DIR / "lenny.json"
WATCH_LATER_STATE = STATE_DIR / "watch_later.json"

PLANNER_SYSTEM_PROMPT = (PROMPTS / "planner.md").read_text()

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


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


# --- Source fetchers ---------------------------------------------------------

def fetch_lenny() -> Optional[dict]:
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

    episode_id = e.get("id") or e.get("guid") or e.get("published", "")
    state = load_json(LENNY_STATE)
    listening_position = (
        state.get("listening_position_seconds", 0)
        if state.get("episode_id") == episode_id
        else 0
    )

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
    results = []
    for name, channel_id in YT_CHANNELS:
        feed = feedparser.parse(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        )
        for video in feed.entries:
            url = video.get("link", "")
            if "/shorts/" in url:
                continue
            desc = ""
            if hasattr(video, "media_description"):
                desc = video.media_description
            elif video.get("summary"):
                desc = video.summary
            results.append({
                "channel": name,
                "title": video.title,
                "published": video.get("published", ""),
                "url": url,
                "description": strip_html(desc)[:800],
            })
            break
    return results


def fetch_bayclub(days_ahead: int = 2) -> list:
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
        except requests.exceptions.RequestException:
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
    """Same mocks as test_planner.py — Gmail MCP integration into standalone
    Python is a future step."""
    return [
        {
            "bucket": "summarize",
            "sender": "thebatch@deeplearning.ai",
            "subject": ("China Thwarts Meta's Agentic Ambition, U.S. Evaluates "
                        "Upcoming Models, AI Diagnoses Mammograms"),
            "snippet": ("This week: China restricts Meta's agentic AI rollout. "
                        "The U.S. evaluates frontier model capabilities ahead "
                        "of release. AI demonstrates diagnostic accuracy on "
                        "mammograms competitive with radiologists."),
            "date": "2026-05-15",
        },
        {
            "bucket": "summarize",
            "sender": "peteryang+podcast@substack.com",
            "subject": "Inside How Anthropic Is Building the Next Claude | Alex Albert",
            "snippet": ("Peter Yang interviews Alex Albert about how "
                        "Anthropic's research team picks model capabilities "
                        "and trains Claude's character."),
            "date": "2026-05-17",
        },
    ]


# --- Planner call ------------------------------------------------------------

def call_planner(planner_input: dict) -> dict:
    print("Calling planner (Claude Sonnet 4.5)...")
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        system=PLANNER_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "Return ONLY the JSON object as described in the system "
                "prompt. No prose around it.\n\n"
                f"```json\n{json.dumps(planner_input, indent=2)}\n```"
            ),
        }],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:].strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    return json.loads(raw)


# --- Segment generators ------------------------------------------------------

def synthesize_tts(text: str, out_path: Path, eleven: ElevenLabs) -> None:
    """Generate one TTS MP3 chunk via ElevenLabs."""
    audio = eleven.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    with open(out_path, "wb") as f:
        for chunk in audio:
            f.write(chunk)


def download_audio(url: str, cache_path: Path) -> Path:
    """Download an MP3 if not already cached."""
    if cache_path.exists():
        print(f"  Cached: {cache_path.name} ({cache_path.stat().st_size/1024/1024:.1f} MB)")
        return cache_path
    print(f"  Downloading: {url[:80]}...")
    resp = requests.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    with open(cache_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            f.write(chunk)
    print(f"  Saved: {cache_path.name} ({cache_path.stat().st_size/1024/1024:.1f} MB)")
    return cache_path


# --- Main pipeline -----------------------------------------------------------

now = datetime.now()
print("=" * 60)
print(f"OnRoute briefing — {now.strftime('%A, %B %d, %Y')}")
print(f"Budget: {TIME_BUDGET_MINUTES} min | Mode: {MODE}")
print("=" * 60)

print("\nFetching candidates...")
candidates = {
    "emails": mock_emails(),
    "lenny_podcast": fetch_lenny(),
    "youtube": fetch_youtube(),
    "bay_club_classes": fetch_bayclub(),
}
print(f"  Emails:           {len(candidates['emails'])}")
print(f"  Lenny:            "
      f"{'present' if candidates['lenny_podcast'] else 'missing'} "
      f"(position: {candidates['lenny_podcast']['listening_position_seconds']}s)")
print(f"  YouTube:          {len(candidates['youtube'])}")
print(f"  Bay Club:         {len(candidates['bay_club_classes'])}")

planner_input = {
    "time_budget_minutes": TIME_BUDGET_MINUTES,
    "mode": MODE,
    "current_date": now.strftime("%Y-%m-%d"),
    "current_day_of_week": now.strftime("%A"),
    "candidates": candidates,
}

playlist = call_planner(planner_input)
print(f"\nPlanner returned {len(playlist.get('segments', []))} segments.")
print(f"Rationale: {playlist.get('rationale', '(none)')}")

# Generate each segment
print("\nGenerating segments...")
eleven = ElevenLabs(api_key=ELEVENLABS_API_KEY)
segment_files = []

for i, seg in enumerate(playlist.get("segments", []), 1):
    seg_type = seg.get("type", "tts")
    label = seg.get("label", f"segment_{i}")
    safe_label = re.sub(r"[^a-z0-9]+", "_", label.lower())[:40]
    out_path = OUTPUT / f"seg_{i:02d}_{safe_label}.mp3"

    if seg_type == "tts":
        print(f"  [{i}/{len(playlist['segments'])}] TTS: {label}")
        synthesize_tts(seg["text"], out_path, eleven)
    elif seg_type == "audio":
        print(f"  [{i}/{len(playlist['segments'])}] AUDIO: {label}")
        # Cache the source MP3 by episode_id-ish filename
        url = seg["audio_url"]
        cache_name = re.sub(r"[^a-zA-Z0-9.]+", "_", url.split("/")[-1])
        cache_path = DOWNLOADS / cache_name
        source = download_audio(url, cache_path)
        full = AudioSegment.from_mp3(source)
        start_ms = seg.get("start_seconds", 0) * 1000
        end_ms = start_ms + seg.get("duration_seconds", 60) * 1000
        clip = full[start_ms:end_ms]
        clip.export(out_path, format="mp3", bitrate="128k")
    else:
        print(f"  [{i}] Unknown segment type {seg_type!r}; skipping.")
        continue

    segment_files.append(out_path)

# Stitch all segments
print("\nStitching segments...")
combined = AudioSegment.empty()
silence = AudioSegment.silent(duration=400)
for i, path in enumerate(segment_files):
    seg = AudioSegment.from_mp3(path)
    combined += seg
    if i < len(segment_files) - 1:
        combined += silence

briefing_name = f"briefing-{now.strftime('%Y-%m-%d')}.mp3"
final_path = OUTPUT / briefing_name
combined.export(final_path, format="mp3", bitrate="128k")
size_mb = final_path.stat().st_size / 1024 / 1024
duration_min = len(combined) / 1000 / 60
print(f"Saved: {final_path}")
print(f"       {size_mb:.1f} MB | {duration_min:.1f} min")

# Update state files
print("\nUpdating state...")

# Lenny position (advance by today's audio duration)
lenny_audio_seg = next(
    (s for s in playlist["segments"]
     if s.get("type") == "audio" and s.get("source") == "lenny"),
    None,
)
if lenny_audio_seg and candidates["lenny_podcast"]:
    new_position = (
        lenny_audio_seg.get("start_seconds", 0)
        + lenny_audio_seg.get("duration_seconds", 0)
    )
    save_json(LENNY_STATE, {
        "episode_id": candidates["lenny_podcast"]["episode_id"],
        "episode_title": candidates["lenny_podcast"]["title"],
        "episode_duration_seconds": candidates["lenny_podcast"]["duration_seconds"],
        "listening_position_seconds": new_position,
        "last_updated": now.isoformat(),
    })
    print(f"  Lenny position: {new_position}s "
          f"({new_position // 60}m of "
          f"{candidates['lenny_podcast']['duration_seconds'] // 60}m total)")

# Watch Later — append new URLs
new_watch_later = playlist.get("watch_later_urls", [])
existing = load_json(WATCH_LATER_STATE).get("items", []) if WATCH_LATER_STATE.exists() else []
known_urls = {item.get("url") for item in existing}
added = 0
for item in new_watch_later:
    if item.get("url") and item["url"] not in known_urls:
        item["added"] = now.isoformat()
        existing.append(item)
        added += 1
save_json(WATCH_LATER_STATE, {"items": existing})
print(f"  Watch Later: +{added} new "
      f"({len(existing)} total in queue)")

# Auto-play
print("\nPlaying briefing...")
subprocess.run(["afplay", str(final_path)])
print("Done.")
