"""Pre-generate one Burmese sample per voice (run once; users then preview for free).
Usage: python generate_voice_samples.py [VoiceName ...]   (no args = all voices; skips existing files)"""
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

from gemini_tts import synthesize_to_file
from voices import SAMPLE_TEXT, VOICES, VOICE_NAMES

OUT = "voice_samples"
os.makedirs(OUT, exist_ok=True)
wanted = sys.argv[1:] or [v["name"] for v in VOICES]
for name in wanted:
    if name not in VOICE_NAMES:
        print(f"skip unknown voice {name}")
        continue
    path = os.path.join(OUT, f"{name}.wav")
    if os.path.exists(path):
        print(f"have {name}")
        continue
    try:
        synthesize_to_file(SAMPLE_TEXT, path, name)
        print(f"ok   {name}", flush=True)
    except Exception as exc:
        print(f"FAIL {name}: {exc}", flush=True)
    time.sleep(1)
