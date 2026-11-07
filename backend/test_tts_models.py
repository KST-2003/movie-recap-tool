"""Same Burmese text, same voice, every TTS model in the pool: 1 request per model (each model has its own quota).
Run: python test_tts_models.py [model ...]   -> model_samples/<model>.wav ; LISTEN to each: is it Burmese, natural, consistent?"""
import os
import subprocess
import sys

from dotenv import load_dotenv
load_dotenv()

import gemini_tts

MODELS = sys.argv[1:] or ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts",
                          "gemini-2.5-pro-preview-tts", "gemini-3.8-flash-lite-tts"]
LINE = ("ဒီအချိန်မှာပဲ သူ့ရဲ့ လျှို့ဝှက်ချက်တစ်ခု ပေါ်လာတော့တယ်။ ဘယ်သူမှ မမျှော်လင့်ခဲ့ဘူး။ "
        "ဒါပေမယ့် အဲဒီညမှာ ဘယ်သူမှ မထင်မှတ်ထားတဲ့ အဖြစ်အပျက်တစ်ခု ဖြစ်သွားခဲ့ပါတယ်။")
os.makedirs("model_samples", exist_ok=True)
for model in MODELS:
    path = f"model_samples/{model}.wav"
    try:
        gemini_tts.synthesize_to_file(LINE, path, "Kore", retries=1, model=model)
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True).stdout.strip()
        print(f"OK     {model}: {float(dur):.1f}s of audio -> {path}")
    except Exception as exc:
        print(f"FAILED {model}: {str(exc)[:200]}")
