# OnRoute — An Agentic Commute Briefing

An AI agent that decides how I should spend my hour. Pulls today's top emails, plays Lenny's latest podcast in his own voice, previews new AI videos worth my time, and rolls Bay Club classes into the mix — composed against my time budget and delivered as a private podcast feed.

Built in Claude Cowork. Listens to me, not the other way around.

## Demo

[![OnRoute walkthrough](docs/dashboard-screenshot.png)](docs/onroute_final_demo.mp4)

*A 60-second walkthrough with an AI avatar (not me) narrated by an ElevenLabs voice is available at [`docs/onroute_final_demo.mp4`](docs/onroute_final_demo.mp4).*

## The Problem

1 hour on the drive. 1 hour walking Wookiee and Penny, my 2 doodles. Same problem either way: I want to catch up on email, the latest in agentic AI, and continue my DeepLearning.AI course — but no tool composes them for me.

Apple Podcasts plays the podcasts I subscribe to, in the order they were published. Gmail shows me every email, in chronological order. YouTube recommends videos based on what gets clicks. None of them know I have exactly 1 hour, that I want to spend most of it on Lenny's interview but also need to know which classes are at the gym tomorrow, and that I'd rather hear a 30-second preview of Mahesh Yadav's new video than have his marketing email read aloud.

Dashboards and feeds are great at showing data. They can't compose it. They can't weigh "Lenny's episode is 99 minutes but I only have 60" against "actually most of those 60 minutes should be Lenny because I'm in learning mode this morning" against "save the YouTube videos for when I'm parked because I want to see the screen." That's the synthesis layer. That's product work.

OnRoute automates that synthesis layer.

## What OnRoute Does

- Pulls top-priority email from Gmail (read-only — agent can create drafts, cannot send)
- Triages each email into 1 of 4 buckets: `skip`, `summarize`, `read-in-full`, `confidential`
- Routes anything in higher-risk categories away from audio playback, so confidential content stays at-desk
- Fetches the latest Lenny's Podcast episode via Substack RSS
- Tracks listening position across days — if today's drive only fits 50 minutes of a 99-minute episode, tomorrow's briefing picks up where I left off
- Pulls new non-Shorts uploads from 2 YouTube channels (DeepLearning.AI and Mahesh Yadav's Agentic AI Institute), summarizes each into a 30-60 second preview, and queues URLs in the podcast episode notes for later viewing
- Fetches today's and tomorrow's Bay Club Pleasanton classes via their public schedule API, filtered to my 7 class types
- Composes a TTS playlist sized to my time budget — connective tissue in a ElevenLabs voice, Lenny in his actual voice
- Delivers as a private RSS feed via GitHub Pages, picked up automatically by Apple Podcasts on my iPhone

## How It Works

OnRoute is built on the Anthropic API using Claude Sonnet 4.5 as the BriefingPlanner agent. The agent autonomously decides which items to include, in what order, with what summarization depth, given today's time budget and mode.

```
Per-source candidate fetchers (Python)
   Gmail MCP (read + drafts only, no send)
   Lenny RSS                                    Listening state
   YouTube RSS × 2 (Shorts filtered out)        (state/lenny.json,
   Bay Club JSON API                             state/watch_later.json)
            ↓                                            ↓
   BriefingPlanner agent (Claude Sonnet 4.5)
            ↓
   JSON playlist with two segment types:
      tts segments (text for ElevenLabs voice)
      audio segments (URL + position + duration for passthrough)
            ↓
   Audio generation
      ElevenLabs TTS per tts segment
      Download + slice per audio segment
      pydub stitch with 400ms silence between segments
            ↓
   Daily briefing MP3 → RSS feed → GitHub Pages → Apple Podcasts → iPhone
```

**The analysis tools (per-source fetchers):**

- `test_gmail` / Gmail MCP — fetches recent inbox threads, runs each through the triage classifier prompt. Returns 4-bucket classification per email. The Gmail MCP server exposes `search_threads`, `get_thread`, `list_labels`, `create_draft`. There is no `send_email` tool. The no-send guarantee is enforced at the MCP server level, not in my code.
- `test_lenny` — parses Lenny's public Substack-hosted RSS feed, returns latest episode metadata plus my current listening position.
- `test_youtube` — fetches YouTube's public per-channel RSS at `youtube.com/feeds/videos.xml?channel_id=...`. No Google Cloud API key. Filters out Shorts (`/shorts/` URLs) before returning.
- `test_bayclub` — Bay Club's schedule page is JavaScript-rendered, but the underlying data comes from a public Azure-hosted JSON API I found via Chrome DevTools' Network tab. No member-portal credentials needed.

**The BriefingPlanner (the agent):**

The planner reads all candidate items + my time budget + mode + current date and produces an ordered playlist of segments. The planner does both selection (which items make it in) and script-writing (what gets spoken) in a single Claude call. Two segment types: `tts` (text for ElevenLabs voice) and `audio` (external MP3 passthrough with start position and duration).

The planner stays under budget. Composition rationale is included in the output so I can see why it chose what it chose — useful for debugging and for tuning the prompt over time.

**The audio pipeline:**

For each `tts` segment, OnRoute calls ElevenLabs with a chosen female voice and the segment text. For the `audio` segment (Lenny), it downloads the source MP3 from Substack (cached after first download) and slices the specified duration from the specified start position using pydub. All segments concatenate with 400ms of silence between them. The final MP3 lands in `output/briefing-YYYY-MM-DD.mp3`.

**The state files:**

`state/lenny.json` tracks which episode I'm in the middle of and where I left off. Tomorrow's briefing reads this and continues where today's left off. `state/watch_later.json` accumulates YouTube URLs that OnRoute previewed but didn't play — the feed generator includes them as tappable links in each day's episode notes.

## The Dashboard

`dashboard/index.html` shows today's composition at a glance: 4 hero metrics, the time-allocation bar with planner rationale, source cards with active candidate counts, the full playlist, Lenny's continuation state with progress bar, and the Watch Later queue.

The dashboard is a static HTML file regenerated each morning. Designed for at-desk tuning (which I rarely need) and for being demoable (which I do, often).

## Quickstart

```
git clone https://github.com/pallavi-oke/onroute.git
cd onroute
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Add your Anthropic API key, ElevenLabs API key, voice ID
python generate_briefing.py
python generate_feed.py
git add docs/ && git commit -m "Today's briefing" && git push
```

Apple Podcasts on iPhone picks up the feed at `https://pallavi-oke.github.io/onroute/feed.xml` within ~30 minutes. Subscribe via Library → ... menu → "Follow a Show by URL."

## What I Learned

**Composition is the product, not sources.** Each source — Gmail, Lenny's RSS, YouTube, Bay Club's API — was 30-60 minutes of integration work. The agentic value is in the BriefingPlanner that decides the mix for my time and mode. A 15-min product, a 60-min product, and a 90-min product are 3 different agents wearing the same skin. Time-budget allocation was the most interesting design problem in the project; the source integrations were the easy part.

**Scoping to 1 user unlocked the build.** A general "AI briefing app" would need to handle every inbox, every podcast taste, every learning interest. OnRoute is for my Gmail, my Lenny, my DeepLearning.AI, my Bay Club, my dog walks. That tight scope let me ship a multi-source agent in 1 weekend instead of a generic product in 6 months. The interesting question isn't "what should everyone want" — it's "what would I actually use every day," and the design follows from there.

**Design the no-send guarantee at the permission layer, not in code.** I considered enforcing "no send" with a code-level rule before plugging into Gmail. Then I noticed the Gmail MCP server exposes `search_threads`, `get_thread`, and `create_draft` — but no `send_email` tool. The capability literally doesn't exist. That's a stronger guarantee than any rule I could write, and it's the architectural pattern I'd reach for anywhere the cost of a wrong agent action is high.

**The connective tissue voice should never duplicate what the source material already does.** First run, the ElevenLabs voice introduced Caitlin Kalinowski, then Lenny's audio started and introduced her again. Felt awkward. Fix was 1 prompt revision: the transition for a fresh episode is "Now for today's Lenny" — minimal — and Lenny's own intro covers the guest. For multi-day continuation, the transition becomes "Picking up where you left off, around the forty-seven minute mark" — which is useful precisely because Lenny doesn't re-introduce the guest mid-episode. The connective tissue adapts based on what the source already provides.

**Hidden public APIs beat scrapers.** Bay Club's schedule page is JavaScript-rendered. The "obvious" path was Playwright (headless browser, ~150 MB of Chromium, slow, fragile). 5 minutes in Chrome DevTools' Network tab revealed the page calls a public Azure-hosted JSON endpoint behind the scenes. No auth, no scraping, no browser overhead. The right way to integrate with most modern sites is to find the underlying API, not to render the page. Transferable to almost any future integration.

**The trusted-sender allowlist is a feedback loop, not a static config.** I added `thebatch@deeplearning.ai` and `myaicommunity@substack.com` to the always-summarize allowlist in the triage prompt. Then I noticed Mahesh's Substack is mostly Maven course marketing, not substantive content — his real content is on his YouTube channel. I removed `myaicommunity@substack.com` from the allowlist. The allowlist gets sharper with use, not at setup time.

**The constraint of the listening surface shapes the interaction model.** I wanted the agent to ask "want to hear the YouTube videos next?" at the end of the briefing — conversational, voice-first. Apple Podcasts is one-way audio; it doesn't listen for responses. The platform constraint forced a different design: pre-compose previews of the YouTube videos as TTS segments, include the URLs as tappable links in episode notes. Hands-free during the drive, intentional during parking. The constraint produced a better design than the original idea.

## Cowork First Impressions

This was my first build in Claude Cowork. Honest 3-line take:

The scheduled-task primitive made the daily cadence feel natural; I didn't have to think about cron jobs or background processes. The MCP ecosystem (Gmail in particular) saved me from writing OAuth flows I'd otherwise have spent 2 hours on. The thing I'd want different: I had to use mock email data in my standalone Python script because the Gmail MCP only runs inside Cowork's context — real Gmail integration requires the daily run to also run inside Cowork via a scheduled task, which is the right architecture but means the standalone testing loop is a step removed from the real one.

## Future Work

- Replace mock email candidates with the real Gmail MCP integration via a Cowork-scheduled daily task
- iOS Shortcut + webhook for hands-free time-budget and mode configuration via Siri / Lock Screen button
- YouTube audio passthrough via yt-dlp (Path A) for hands-free continuation after the main briefing — optional; the current Path B episode-notes approach is fine for now
- Adaptive mode inference based on calendar context — "you have a 2pm meeting; today is an executive-mode day"
- Sender allowlist learning from feedback signals over time
- Multi-source de-duplication (the same news in The Batch and on Lenny shouldn't get told twice)
- Authenticated hosting (Render basic auth) for the RSS feed before real Gmail content is published

## Tech Stack

Python · Anthropic Claude Sonnet 4.5 · ElevenLabs · Gmail MCP · pydub · feedparser · python-dotenv · Anthropic SDK · GitHub Pages

## About

OnRoute is the latest in a portfolio of agentic AI prototypes by [Pallavi Oke](https://github.com/pallavi-oke) — exploring how autonomous agents can own end-to-end product workflows in ad tech, real estate, insurance, and now personal-productivity space.

Also see: [AdRx](https://github.com/pallavi-oke/adrx) (campaign performance agent), [ContentForge](https://github.com/pallavi-oke/contentforge) (multi-agent content pipeline), [PolicyPilot](https://github.com/pallavi-oke/policypilot) (ad compliance agent), [MerchantMind / Sentinel Vantage](https://github.com/pallavi-oke/merchantmind) (AI-driven corporate rewards).
