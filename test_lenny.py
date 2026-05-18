"""
test_lenny.py — Fetch and print the latest Lenny's Podcast episode metadata.

Hits Lenny's public Substack-hosted RSS feed via `feedparser`, prints the
latest episode's title, publish date, duration, audio URL, and description
snippet. This is the read-side primitive the BriefingPlanner will use in
Phase 3 to decide: include the full episode as passthrough audio, or
generate a 5-min summary from the description, depending on time budget.

Run: python test_lenny.py
"""

import sys
from datetime import datetime
from html import unescape

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

# Lenny's Podcast public RSS feed (Substack-hosted)
LENNY_FEED = "https://api.substack.com/feed/podcast/10845.rss"


def strip_html(text: str) -> str:
    """Crude HTML strip for description preview only."""
    import re
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def format_duration(seconds_str: str) -> str:
    """itunes:duration can be HH:MM:SS, MM:SS, or raw seconds. Normalize."""
    if not seconds_str:
        return "unknown"
    if ":" in seconds_str:
        return seconds_str
    try:
        total = int(seconds_str)
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
    except ValueError:
        return seconds_str


print(f"Fetching: {LENNY_FEED}")
feed = feedparser.parse(LENNY_FEED)

if feed.bozo:
    print(f"WARNING: feed parse error: {feed.bozo_exception}")

print(f"Podcast: {feed.feed.get('title', 'unknown')}")
print(f"Episodes in feed: {len(feed.entries)}")
print()

if not feed.entries:
    print("ERROR: No episodes found.")
    sys.exit(1)

# Latest episode is feed.entries[0]
latest = feed.entries[0]

print("=== Latest Episode ===")
print(f"Title:       {latest.title}")
print(f"Published:   {latest.get('published', 'unknown')}")
print(f"Duration:    {format_duration(latest.get('itunes_duration', ''))}")

# Audio URL lives in the enclosure
audio_url = None
for link in latest.get("links", []):
    if link.get("rel") == "enclosure" and "audio" in link.get("type", ""):
        audio_url = link.get("href")
        break
if not audio_url and latest.get("enclosures"):
    audio_url = latest.enclosures[0].get("href")

print(f"Audio URL:   {audio_url}")

# Description / summary
description = latest.get("summary") or latest.get("description") or ""
description_clean = strip_html(description)
print(f"Description: {description_clean[:300]}...")
print()
print("This metadata will feed the BriefingPlanner in Phase 3.")
