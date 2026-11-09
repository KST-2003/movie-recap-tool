"""Real-API check of Google Cloud Text-to-Speech (Gemini voices). Usage: venv/bin/python test_cloud_tts.py [model] [lang]
Saves cloud_tts_test/<model>.wav and prints latency + a burst test (6 parallel requests)."""
import base64, os, sys, time, wave, concurrent.futures as cf
from dotenv import load_dotenv
load_dotenv()
import google.auth.transport.requests as gr
from google.oauth2 import service_account
import requests

model = sys.argv[1] if len(sys.argv) > 1 else "gemini-2.5-flash-tts"
lang = sys.argv[2] if len(sys.argv) > 2 else "my-MM"
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ ကျွန်တော်တို့ ရုပ်ရှင်ကားတစ်ကား အကြောင်း ပြောပြပါမယ်။"
creds = service_account.Credentials.from_service_account_file(
    os.environ["GCP_SERVICE_ACCOUNT_FILE"], scopes=["https://www.googleapis.com/auth/cloud-platform"])

def call(i=0):
    creds.refresh(gr.Request()) if not creds.valid else None
    body = {"input": {"text": TEXT},
            "voice": {"languageCode": lang, "name": "Kore", "modelName": model},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}}
    t = time.time()
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", json=body, timeout=90,
                      headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": os.environ["GCP_PROJECT_ID"]})
    return r, time.time() - t

r, dt = call()
print("status", r.status_code, f"{dt:.1f}s")
if r.status_code != 200:
    print(r.text[:800]); sys.exit(1)
os.makedirs("cloud_tts_test", exist_ok=True)
pcm = base64.b64decode(r.json()["audioContent"])
out = f"cloud_tts_test/{model}.wav"
open(out, "wb").write(pcm)  # LINEAR16 response already has a WAV header
with wave.open(out) as w: print("saved", out, f"{w.getnframes() / w.getframerate():.1f}s audio")
print("burst of 6 parallel requests...")
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(call, range(6)))
print("statuses", [x[0].status_code for x in res], "latencies", [round(x[1], 1) for x in res])
for x, _ in res:
    if x.status_code != 200: print(x.text[:400]); break
