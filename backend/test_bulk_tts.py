"""Real-Gemini experiment for batched voice requests (uses 3-5 TTS requests; run when your daily quota is free).
   python test_bulk_tts.py            # tries 3, 8 and 16 sentences in one request
Prints, per run: request time, audio length, whether the pause-based split was trusted and each clip's length.
Listen to bulk_test/*.wav afterwards to check that sentences are cut cleanly and the voice stays consistent."""
import os
import subprocess
import time

from dotenv import load_dotenv
load_dotenv()

import bulk_tts
from gemini_tts import synthesize_to_file

SENTENCES = [
    "ညီအစ်မနှစ်ယောက် မိတ်ဆက်ပွဲမှာ အခွင့်အရေးကို ဖျက်ဆီးဖို့ ကြိုးစားနေကြပါတယ်။",
    "ညီမက ဝက်ပေါင်ကို အရသာခံစားနေပါတယ်။",
    "အစ်မက စိတ်ဆိုးသွားပေမယ့် ဘာမှမပြောပါဘူး။",
    "အဲဒီညမှာ ဧည့်သည်အားလုံး စားပွဲမှာ စုံညီထိုင်နေကြပါတယ်။",
    "ဦးလေးက ဟင်းပွဲကို ဖွင့်ပြီး ပြုံးပြတယ်။",
    "ကလေးတွေက အံ့သြစွာ ကြည့်နေကြတယ်။",
    "ဒီနေ့ညက သူတို့အတွက် မမေ့နိုင်တဲ့ည ဖြစ်လာမယ်။",
    "ဒါပေမယ့် ဘယ်သူမှ ဘာဖြစ်မယ်ဆိုတာ မသိကြသေးပါဘူး။",
] * 2
os.makedirs("bulk_test", exist_ok=True)


def dur(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout)


for n in (3, 8, 16):
    texts = SENTENCES[:n]
    big = f"bulk_test/bulk_{n}.wav"
    t = time.time()
    try:
        synthesize_to_file(bulk_tts.JOINER.join(texts), big)
    except Exception as exc:
        print(f"{n} sentences: FAILED after {time.time() - t:.1f}s: {exc}")
        break
    took = time.time() - t
    spans = bulk_tts.find_spans(big, texts)
    print(f"{n} sentences ({sum(map(len, texts))} chars): {took:.1f}s request, {dur(big):.1f}s audio, "
          f"split {'OK' if spans else 'NOT TRUSTED'}")
    if spans:
        bulk_tts.cut(big, spans, [f"bulk_test/bulk_{n}_clip{i + 1}.wav" for i in range(n)])
        print("   clip lengths:", [round(b - a, 1) for a, b in spans])
