"""
generate_feed.py — Generate the OnRoute RSS feed.

Finds today's briefing MP3 in output/, copies it into docs/audio/ for GitHub
Pages hosting, and writes docs/feed.xml. The episode description includes the
YouTube watch-later links pulled from state/watch_later.json.

Run AFTER generate_briefing.py.

Run: python generate_feed.py

PRIVACY NOTE: docs/ is served publicly via GitHub Pages on the main onroute
repo. v1 hosting is public-but-obscure. Briefings contain mocked emails for
now, so safe to publish. Switch to authenticated hosting (Render basic auth)
before real Gmail integration in v1.1.
"""

import json
import shutil
from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path

# --- Configuration -----------------------------------------------------------
PODCAST_TITLE = "OnRoute"
PODCAST_DESCRIPTION = "Pallavi's personal commute briefing agent."
PODCAST_AUTHOR = "Pallavi Oke"
PODCAST_LANGUAGE = "en-us"
BASE_URL = "https://pallavi-oke.github.io/onroute"

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).parent
output_dir = ROOT / "output"
state_dir = ROOT / "state"
docs_dir = ROOT / "docs"
audio_dir = docs_dir / "audio"
feed_path = docs_dir / "feed.xml"

audio_dir.mkdir(parents=True, exist_ok=True)


def load_watch_later_today():
    """Pull Watch Later items added today, for inclusion in episode notes."""
    watch_later_path = state_dir / "watch_later.json"
    if not watch_later_path.exists():
        return []
    try:
        data = json.loads(watch_later_path.read_text())
    except json.JSONDecodeError:
        return []
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        item for item in data.get("items", [])
        if item.get("added", "").startswith(today)
    ]


def build_episode_description(watch_later_items: list) -> str:
    """RSS episode description as HTML, including YouTube links for Path B."""
    lines = [
        "<p>Today's OnRoute briefing covers your inbox highlights, "
        "Lenny's latest podcast (multi-day continuation), Bay Club "
        "Pleasanton classes for today and tomorrow, plus quick previews "
        "of new AI videos worth watching later.</p>",
    ]
    if watch_later_items:
        lines.append("<h3>Mentioned in this briefing (tap to watch):</h3>")
        lines.append("<ul>")
        for item in watch_later_items:
            title = escape(item.get("title", "Untitled"))
            channel = escape(item.get("channel", ""))
            url = escape(item.get("url", "#"))
            channel_prefix = f"<em>{channel}:</em> " if channel else ""
            lines.append(
                f'<li>{channel_prefix}<a href="{url}">{title}</a></li>'
            )
        lines.append("</ul>")
    return "\n".join(lines)


# --- Find today's briefing ---------------------------------------------------
# Prefer briefing-YYYY-MM-DD.mp3; fall back to plain briefing.mp3 (test runs).
today_str = datetime.now().strftime("%Y-%m-%d")
candidates = sorted(output_dir.glob("briefing-*.mp3"))
if not candidates:
    candidates = sorted(output_dir.glob("briefing.mp3"))
if not candidates:
    print("No briefings found in output/. Run generate_briefing.py first.")
    raise SystemExit(1)

# Use the most recently modified
latest_briefing = max(candidates, key=lambda p: p.stat().st_mtime)
print(f"Latest briefing: {latest_briefing}")


# --- Copy MP3 into docs/audio/ ----------------------------------------------
dest = audio_dir / latest_briefing.name
shutil.copy(latest_briefing, dest)
file_size = dest.stat().st_size
print(f"Copied to: {dest} ({file_size / 1024:.1f} KB)")


# --- Build feed item --------------------------------------------------------
now = datetime.now(timezone.utc)
audio_url = f"{BASE_URL}/audio/{latest_briefing.name}"
title = f"OnRoute Briefing — {now.strftime('%A, %B %d, %Y')}"

watch_later_today = load_watch_later_today()
description_html = build_episode_description(watch_later_today)

item_xml = f"""    <item>
      <title>{escape(title)}</title>
      <description><![CDATA[{description_html}]]></description>
      <pubDate>{format_datetime(now)}</pubDate>
      <enclosure url="{audio_url}" length="{file_size}" type="audio/mpeg" />
      <guid isPermaLink="false">{audio_url}</guid>
      <itunes:summary>{escape(PODCAST_DESCRIPTION)}</itunes:summary>
    </item>"""

rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{PODCAST_TITLE}</title>
    <link>{BASE_URL}</link>
    <description>{PODCAST_DESCRIPTION}</description>
    <language>{PODCAST_LANGUAGE}</language>
    <itunes:author>{PODCAST_AUTHOR}</itunes:author>
    <itunes:summary>{PODCAST_DESCRIPTION}</itunes:summary>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Technology" />
{item_xml}
  </channel>
</rss>
"""

feed_path.write_text(rss)

print(f"Wrote: {feed_path}")
print(f"Watch Later links in episode notes: {len(watch_later_today)}")
print()
print("Next:")
print("  git add docs/")
print("  git commit -m 'Publish today's briefing'")
print("  git push")
print()
print(f"  Then refresh Apple Podcasts on iPhone (pull-to-refresh in OnRoute show).")
print(f"  Today's episode: '{title}' should appear.")
