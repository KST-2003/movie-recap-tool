"""Make a sample for every character look (skips the ones that exist). ~1 TTS request each, paced by the model pool limiter.
Run: python generate_look_samples.py   (add --force to redo all)"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()
import gemini_tts  # noqa: E402
from looks import LOOK_SAMPLE_TEXT, LOOKS, compose  # noqa: E402

import tts_pool  # noqa: E402

MODEL = tts_pool.models()[0][0]   # the model films use first (the default one can hang: it did on 2026-11-07)
only = [a for a in sys.argv[1:] if not a.startswith("--")]
os.makedirs("look_samples", exist_ok=True)
for lid, _g, label, voice, instr in LOOKS:
    path = f"look_samples/{lid}.wav"
    if only and lid not in only:
        continue
    if os.path.exists(path) and "--force" not in sys.argv and not only:
        continue
    try:
        gemini_tts.synthesize_to_file(compose(instr, LOOK_SAMPLE_TEXT), path, voice, model=MODEL)
        print("ok", lid, flush=True)
    except gemini_tts.QuotaExceeded as exc:
        print("quota reached, stopping:", str(exc)[:100])
        break
    except Exception as exc:
        print("FAILED", lid, str(exc)[:120], flush=True)
print("done")
