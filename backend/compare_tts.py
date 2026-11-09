"""Compare AI Studio and Google Cloud TTS on the same Burmese lines. Real requests (about 40).
Usage: venv/bin/python compare_tts.py   ->  compare_tts/<provider>__<model>__<voice>__<n>.wav + a table.
Objective check: Gemini (text) listens to each clip and writes what it heard; we score similarity to the script
(a heard-back score near 1.0 = clear, correct Burmese; it does NOT measure how pleasant the voice is - listen too)."""
import base64, difflib, io, os, sys, time, wave, concurrent.futures as cf
from dotenv import load_dotenv
load_dotenv()
import requests
import gemini_tts
from google.oauth2 import service_account
import google.auth.transport.requests as gr
from google.genai import types

LINES = [
    "မင်္ဂလာပါ။ ဒီနေ့ ကျွန်တော်တို့ ရုပ်ရှင်ကားတစ်ကား အကြောင်း ပြောပြပါမယ်။",
    "သူမက တံခါးကို ဖွင့်လိုက်တဲ့အခါ အခန်းထဲမှာ ဘယ်သူမှ မရှိတော့ဘူး။ ဒါပေမယ့် စားပွဲပေါ်မှာ စာတစ်စောင် ချန်ထားခဲ့တယ်။",
    "မလုပ်ပါနဲ့! ကျွန်တော့်ကို လွှတ်ပေးပါ! ဒီအတွက် မင်းနောင်တရရလိမ့်မယ်!",
    "နှစ်ပေါင်းများစွာ ကြာပြီးနောက်မှာတော့ သူတို့နှစ်ယောက် ပြန်ဆုံကြပြီး အရင်ကလို ပြုံးပြုံးရွှင်ရွှင် စကားပြောခဲ့ကြတယ်။",
]
VOICES = ["Kore", "Charon"]  # one female, one male
AISTUDIO = ["gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts"]
CLOUD = ["gemini-2.5-flash-tts", "gemini-2.5-pro-tts"]
os.makedirs("compare_tts", exist_ok=True)

creds = service_account.Credentials.from_service_account_file(
    os.environ["GCP_SERVICE_ACCOUNT_FILE"], scopes=["https://www.googleapis.com/auth/cloud-platform"])

def cloud(text, voice, model, path):
    if not creds.valid: creds.refresh(gr.Request())
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", timeout=120,
        headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": os.environ["GCP_PROJECT_ID"]},
        json={"input": {"text": text}, "voice": {"languageCode": "my-MM", "name": voice, "modelName": model},
              "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}})
    r.raise_for_status()
    open(path, "wb").write(base64.b64decode(r.json()["audioContent"]))

def studio(text, voice, model, path):
    gemini_tts.synthesize_to_file(text, path, voice=voice, model=model, retries=2)

def seconds(path):
    with wave.open(path) as w: return w.getnframes() / w.getframerate()

def heard(path):
    data = open(path, "rb").read()
    resp = gemini_tts.get_text_client().models.generate_content(
        model=os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash"),
        contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"),
                  "Transcribe this Burmese audio exactly as spoken, in Burmese script. Output only the transcript."])
    return (resp.text or "").strip()

def norm(s): return "".join(ch for ch in s if ch.isalnum() or "က" <= ch <= "႟")

def job(args):
    kind, model, voice, i = args
    path = f"compare_tts/{kind}__{model}__{voice}__{i}.wav"
    t = time.time()
    try:
        (cloud if kind == "cloud" else studio)(LINES[i], voice, model, path)
        lat = time.time() - t
        score = difflib.SequenceMatcher(None, norm(LINES[i]), norm(heard(path))).ratio()
        return kind, model, voice, i, lat, seconds(path), score, ""
    except Exception as e:
        return kind, model, voice, i, time.time() - t, 0, 0, str(e)[:100]

tasks = [(k, m, v, i) for k, ms in (("cloud", CLOUD), ("studio", AISTUDIO)) for m in ms for v in VOICES for i in range(len(LINES))]
rows = []
# Cloud: all in parallel (it has room). AI Studio: 2 at a time, it allows ~9 requests/min/model.
with cf.ThreadPoolExecutor(4) as ex:
    for r in ex.map(job, [t for t in tasks if t[0] == "cloud"]): rows.append(r)
for t in [t for t in tasks if t[0] == "studio"]:
    rows.append(job(t)); time.sleep(7)  # stay under 10 requests/minute for a model

print(f"{'provider':7} {'model':32} {'ok':>4} {'latency':>8} {'sec/line':>8} {'heard-back':>10}")
for kind in ("cloud", "studio"):
    for m in (CLOUD if kind == "cloud" else AISTUDIO):
        rs = [r for r in rows if r[1] == m and r[0] == kind]
        good = [r for r in rs if not r[7]]
        if good:
            print(f"{kind:7} {m:32} {len(good)}/{len(rs)} {sum(r[4] for r in good)/len(good):7.1f}s {sum(r[5] for r in good)/len(good):7.1f}s {sum(r[6] for r in good)/len(good):10.2f}")
        else:
            print(f"{kind:7} {m:32} 0/{len(rs)}   {rs[0][7]}")
print("errors:", sorted({(r[1], r[7]) for r in rows if r[7]})[:6])
