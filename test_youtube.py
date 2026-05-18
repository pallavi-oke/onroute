"""
test_youtube.py — Fetch latest videos from tracked YouTube channels.

YouTube exposes free public RSS feeds at:
    https://www.youtube.com/feeds/videos.xml?channel_id=<CHANNEL_ID>

No Google Cloud API key, no OAuth, no quota concerns. Just feedparser.

This script prints the latest 3 uploads from each tracked channel so we can
verify the metadata pipe. In Phase 3, the BriefingPlanner will use this to surface
"new since last briefing" videos to the user.

Run: python test_youtube.py
"""

import sys
from datetime import datetime
from html import unescape

try:
    import feedparser
except ImportError:
    print("ERROR: feedparser not installed. Run: pip install feedparser")
    sys.exit(1)

# Tracked YouTube channels. Add or remove as Pallavi discovers more sources.
CHANNELS = [
    {
        "name": "DeepLearning.AI",
        "channel_id": "UCcIXc5mJsHVYTZR1maL5l9w",
        "why": "Andrew Ng's channel; course content + AI announcements.",
    },
    {
        "name": "Agentic AI Institute (Mahesh Yadav)",
        "channel_id": "UCPnDl-FpDXdPWKVRRV5V7og",
        "why": "AI PM content, agentic systems, MLOps. Free version of his Maven course.",
    },
]


def strip_html(text: str) -> str:
    """Crude HTML strip for description preview only."""
    import re
    return unescape(re.sub(r"<[^>]+>", "", text)).strip()


def fetch_channel(channel: dict) -> None:
    """Fetch and print latest 3 uploads from a single channel."""
    feed_url = (
        f"https://www.youtube.com/feeds/videos.xml?"
        f"channel_id={channel['channel_id']}"
    )
    print(f"\n{'=' * 60}")
    print(f"Channel: {channel['name']}")
    print(f"Why:     {channel['why']}")
    print(f"Feed:    {feed_url}")
    print("=" * 60)

    feed = feedparser.parse(feed_url)

    if feed.bozo:
        print(f"WARNING: feed parse error: {feed.bozo_exception}")
        return

    total_entries = len(feed.entries)
    print(f"Videos in feed (total, including Shorts): {total_entries}")

    if not feed.entries:
        print("No videos found.")
        return

    # Filter out YouTube Shorts. Shorts URLs contain "/shorts/" while regular
    # episodes are "/watch?v=...". Shorts are 30-60sec promo clips; they don't
    # work for audio briefings. Walk the full feed and collect the first 3
    # non-Shorts.
    full_videos = []
    shorts_skipped = 0
    for video in feed.entries:
        url = video.get("link", "")
        if "/shorts/" in url:
            shorts_skipped += 1
            continue
        full_videos.append(video)
        if len(full_videos) >= 3:
            break

    print(f"Shorts skipped: {shorts_skipped}")
    print(f"Full episodes found: {len(full_videos)}")

    if not full_videos:
        print("\n  (No full episodes in the recent feed — channel posted only Shorts.)")
        return

    print("\nLatest 3 full episodes:")
    for i, video in enumerate(full_videos, 1):
        title = video.get("title", "untitled")
        published = video.get("published", "unknown")
        video_url = video.get("link", "")

        description = ""
        if hasattr(video, "media_description"):
            description = video.media_description
        elif video.get("summary"):
            description = video.summary

        description_clean = strip_html(description)[:200]

        print(f"\n  [{i}] {title}")
        print(f"      Published: {published}")
        print(f"      URL:       {video_url}")
        print(f"      Preview:   {description_clean}...")


for channel in CHANNELS:
    fetch_channel(channel)

print()
print("Next: BriefingPlanner will pick newest video since last briefing,")
print("optionally generate a summary via Claude, and surface as a segment.")
