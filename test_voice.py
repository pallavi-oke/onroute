"""
test_voice.py — First proof-of-concept for OnRoute's TTS pipeline.

Generates a short MP3 of your voice clone reading a test phrase,
saves it to output/test_briefing.mp3, then auto-plays it through
your laptop speakers.

Run with: python test_voice.py
"""

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load credentials from .env (file is gitignored, never committed)
load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID")

if not API_KEY:
    print("ERROR: ELEVENLABS_API_KEY not found in .env")
    sys.exit(1)

if not VOICE_ID:
    print("ERROR: ELEVENLABS_VOICE_ID not found in .env")
    sys.exit(1)

try:
    from elevenlabs.client import ElevenLabs
except ImportError:
    print("ERROR: elevenlabs package not installed.")
    print("Run: pip install elevenlabs")
    sys.exit(1)

# The test phrase. Short enough to keep ElevenLabs character cost minimal.
TEXT = "Good morning. This is OnRoute. Today's briefing is starting."

print(f"Voice ID:  {VOICE_ID[:8]}...{VOICE_ID[-4:]}")
print(f"Text:      {TEXT!r}")
print("Generating audio...")

client = ElevenLabs(api_key=API_KEY)

# Modern SDK pattern: text_to_speech.convert returns a generator of bytes.
# eleven_multilingual_v2 is the highest-quality model; good default for pre-generated
# briefings where latency doesn't matter as much as quality.
audio_stream = client.text_to_speech.convert(
    voice_id=VOICE_ID,
    text=TEXT,
    model_id="eleven_multilingual_v2",
    output_format="mp3_44100_128",
)

# Write to disk (output/ is gitignored)
output_path = Path("output/test_briefing.mp3")
output_path.parent.mkdir(parents=True, exist_ok=True)

with open(output_path, "wb") as f:
    for chunk in audio_stream:
        f.write(chunk)

size_kb = output_path.stat().st_size / 1024
print(f"Saved:     {output_path} ({size_kb:.1f} KB)")
print("Playing...")

# afplay is built into macOS, no extra install required
subprocess.run(["afplay", str(output_path)])

print("Done.")
