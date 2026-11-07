"""Make a sample for every character look (skips the ones that exist). ~1 TTS request each, paced by the model pool limiter.
Run: python generate_look_samples.py   (add --force to redo all)"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
import gemini_tts  # noqa: E402
from looks import LOOK_SAMPLE_TEXT, LOOKS, compose  # noqa: E402

os.makedirs("look_samples", exist_ok=True)
for lid, _g, label, voice, instr in LOOKS:
    path = f"look_samples/{lid}.wav"
    if os.path.exists(path) and "--force" not in sys.argv:
        continue
    try:
        gemini_tts.synthesize_to_file(compose(instr, LOOK_SAMPLE_TEXT), path, voice)
        print("ok", lid, flush=True)
    except gemini_tts.QuotaExceeded as exc:
        print("quota reached, stopping:", str(exc)[:100])
        break
    except Exception as exc:
        print("FAILED", lid, str(exc)[:120], flush=True)
print("done")
