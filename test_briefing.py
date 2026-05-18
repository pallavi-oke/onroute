"""
test_briefing.py — Prove end-to-end stitched briefing.

Generates two TTS segments (intro + one email summary), stitches them
into a single MP3 using pydub with a brief silence between segments,
saves to output/briefing.mp3, and plays the result.

This proves the audio-stitching pipeline. Real briefings will use the
same pattern with N segments composed by the BriefingPlanner.

Run: python test_briefing.py

Prerequisite: ffmpeg installed system-wide (brew install ffmpeg on Mac).
pydub depends on ffmpeg for MP3 encoding/decoding.
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

if not API_KEY or not VOICE_ID:
    print("ERROR: Missing ELEVENLABS credentials in .env")
    sys.exit(1)

try:
    from elevenlabs.client import ElevenLabs
except ImportError:
    print("ERROR: elevenlabs not installed. Run: pip install elevenlabs")
    sys.exit(1)

try:
    from pydub import AudioSegment
except ImportError:
    print("ERROR: pydub not installed. Run: pip install pydub")
    sys.exit(1)

# The proof-of-concept briefing: intro + one summary.
# Later, the BriefingPlanner agent will produce these segments dynamically.
SEGMENTS = [
    "Good morning. You have one update worth catching up on this morning.",
    (
        "Peter Yang published a new Substack interview with Alex Albert on "
        "how Anthropic picks model capabilities and trains Claude's character. "
        "Worth a listen later."
    ),
]

client = ElevenLabs(api_key=API_KEY)


def synthesize(text: str, output_path: Path) -> None:
    """Generate an MP3 for one text segment via ElevenLabs."""
    print(f"  Generating: {text[:70]}...")
    audio_stream = client.text_to_speech.convert(
        voice_id=VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    with open(output_path, "wb") as f:
        for chunk in audio_stream:
            f.write(chunk)
    size_kb = output_path.stat().st_size / 1024
    print(f"  Saved: {output_path} ({size_kb:.1f} KB)")


# Ensure output dir exists (gitignored)
output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

# Step 1: Generate each segment as its own MP3
print(f"Generating {len(SEGMENTS)} segments...")
segment_paths = []
for i, text in enumerate(SEGMENTS):
    path = output_dir / f"segment_{i:02d}.mp3"
    synthesize(text, path)
    segment_paths.append(path)

# Step 2: Stitch the segments. Add a 400ms silence between each for breathing room.
print("\nStitching segments...")
combined = AudioSegment.empty()
silence = AudioSegment.silent(duration=400)  # 400ms

for i, path in enumerate(segment_paths):
    segment = AudioSegment.from_mp3(path)
    combined += segment
    if i < len(segment_paths) - 1:
        combined += silence

# Step 3: Export the final combined briefing
final_path = output_dir / "briefing.mp3"
combined.export(final_path, format="mp3", bitrate="128k")

size_kb = final_path.stat().st_size / 1024
duration_sec = len(combined) / 1000
print(f"Combined: {final_path} ({size_kb:.1f} KB, {duration_sec:.1f} sec)")
print("\nPlaying combined briefing...")

subprocess.run(["afplay", str(final_path)])
print("Done.")
