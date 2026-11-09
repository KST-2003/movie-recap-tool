"""Real-API check of Azure Neural TTS in Burmese. Needs AZURE_SPEECH_KEY + AZURE_SPEECH_REGION in backend/.env.
Run: venv/bin/python test_azure_tts.py   -> azure_tts_test/<voice>__<n>.wav, latency, a burst of 12 parallel requests, and a
heard-back score (Gemini transcribes each clip; 1.0 = clear, correct Burmese; it does not measure how pleasant the voice is)."""
import concurrent.futures as cf
import difflib
import os
import sys
import time
import wave
from xml.sax.saxutils import escape

import requests
from dotenv import load_dotenv

load_dotenv()
KEY, REGION = os.getenv("AZURE_SPEECH_KEY", ""), os.getenv("AZURE_SPEECH_REGION", "")
if not KEY or not REGION:
    sys.exit("Set AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in backend/.env first.")
LINES = [
    "မင်္ဂလာပါ။ ဒီနေ့ ကျွန်တော်တို့ ရုပ်ရှင်ကားတစ်ကား အကြောင်း ပြောပြပါမယ်။",
    "သူမက တံခါးကို ဖွင့်လိုက်တဲ့အခါ အခန်းထဲမှာ ဘယ်သူမှ မရှိတော့ဘူး။ ဒါပေမယ့် စားပွဲပေါ်မှာ စာတစ်စောင် ချန်ထားခဲ့တယ်။",
    "မလုပ်ပါနဲ့! ကျွန်တော့်ကို လွှတ်ပေးပါ! ဒီအတွက် မင်းနောင်တရရလိမ့်မယ်!",
]
VOICES = ["my-MM-ThihaNeural", "my-MM-NilarNeural"]
os.makedirs("azure_tts_test", exist_ok=True)


def synth(text: str, voice: str, path: str, pitch="0%", rate="0%") -> float:
    ssml = (f'<speak version="1.0" xml:lang="my-MM" xmlns="http://www.w3.org/2001/10/synthesis"><voice name="{voice}">'
            f'<prosody pitch="{pitch}" rate="{rate}">{escape(text)}</prosody></voice></speak>')
    t = time.time()
    r = requests.post(f"https://{REGION}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode("utf-8"), timeout=60,
                      headers={"Ocp-Apim-Subscription-Key": KEY, "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:200]}")
    open(path, "wb").write(r.content)
    return time.time() - t


def heard(path: str) -> str:
    import gemini_tts
    from google.genai import types
    r = gemini_tts.get_text_client().models.generate_content(
        model=os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash"),
        contents=[types.Part.from_bytes(data=open(path, "rb").read(), mime_type="audio/wav"),
                  "Transcribe this Burmese audio exactly as spoken, in Burmese script. Output only the transcript."])
    return (r.text or "").strip()


norm = lambda s: "".join(c for c in s if c.isalnum())  # noqa: E731
for v in VOICES:
    for i, line in enumerate(LINES):
        p = f"azure_tts_test/{v}__{i}.wav"
        dt = synth(line, v, p)
        with wave.open(p) as w:
            secs = w.getnframes() / w.getframerate()
        score = difflib.SequenceMatcher(None, norm(line), norm(heard(p))).ratio()
        print(f"{v:20} line {i}: {dt:4.1f}s to make, {secs:4.1f}s audio, heard-back {score:.2f}", flush=True)
print("burst: 12 parallel requests...")
t = time.time()
with cf.ThreadPoolExecutor(12) as ex:
    res = list(ex.map(lambda i: synth(LINES[i % 3], VOICES[0], f"azure_tts_test/burst{i}.wav"), range(12)))
print(f"all 12 ok in {time.time() - t:.1f}s (each {min(res):.1f}-{max(res):.1f}s)")
