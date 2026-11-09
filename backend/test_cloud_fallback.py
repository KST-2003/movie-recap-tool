"""Offline test: Google Cloud TTS as the pool's fallback (no request is sent). Run: python test_cloud_fallback.py"""
import json
import os
import tempfile

tmp = tempfile.mkdtemp()
key = f"{tmp}/key.json"
open(key, "w").write("{}")
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", GCP_PROJECT_ID="demo-project", GCP_SERVICE_ACCOUNT_FILE=key, CLOUD_TTS="1",
                  TTS_MODELS="gemini-3.8-flash-tts:10:100,gemini-2.5-flash-preview-tts:10:100")

import cloud_tts  # noqa: E402
import gemini_tts  # noqa: E402
import tts_pool  # noqa: E402
from looks import compose_emotion  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


names = [m for m, _, _ in tts_pool.models()]
ok(names == ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts", "cloud/gemini-2.5-flash-tts", "cloud/gemini-2.5-pro-tts"], f"cloud models come last: {names}")
ok(dict((m, (a, b)) for m, a, b in tts_pool.models())["cloud/gemini-2.5-flash-tts"] == (30, 5000), "cloud soft limits 30/min, 5000/day")

# AI Studio models still have requests -> a job picks the first one, not Cloud
ok(tts_pool.Chooser(10).get() == "gemini-3.8-flash-tts", "AI Studio is preferred while it has requests")

# use both AI Studio models up -> the job moves to Cloud
os.makedirs(f"{tmp}/data", exist_ok=True)
json.dump({"day": tts_pool._today(), "counts": {"gemini-3.8-flash-tts": 100, "gemini-2.5-flash-preview-tts": 100}}, open(tts_pool.USAGE_FILE, "w"))
ch = tts_pool.Chooser(10)
ok(ch.get() == "cloud/gemini-2.5-flash-tts", f"both AI Studio models used up -> {ch.get()}")
ok(not tts_pool.all_blocked(), "pool is not 'all blocked' while Cloud has requests")

# a model that Google refused for the day (429 per day) -> switch while running
tts_pool.USAGE_FILE and json.dump({"day": tts_pool._today(), "counts": {}}, open(tts_pool.USAGE_FILE, "w"))
ch = tts_pool.Chooser(10)
ok(ch.get() == "gemini-3.8-flash-tts", "fresh day: AI Studio again")
gemini_tts._block("quota exceeded retry in 5h", "gemini-3.8-flash-tts")
gemini_tts._block("quota exceeded retry in 5h", "gemini-2.5-flash-preview-tts")
ch.failed("gemini-3.8-flash-tts")
ok(ch.get() == "cloud/gemini-2.5-flash-tts", "mid-video 'daily limit' switches to Cloud")
ok(ch.switches == [("gemini-3.8-flash-tts", "cloud/gemini-2.5-flash-tts")], "the switch is recorded (the user gets a warning)")
import pipeline  # noqa: E402
ok("slightly different voice" in pipeline.VOICE_SWITCH_WARNING, "warning text exists")

# synthesize_to_file sends cloud models to cloud_tts (voice, text, model name)
calls = []
cloud_tts.synthesize = lambda text, path, voice, model, timeout=0: (calls.append((text, voice, model)), open(path, "wb").write(b"RIFFxxxx"))[0]
gemini_tts.synthesize_to_file("မင်္ဂလာပါ", f"{tmp}/a.wav", "Kore", model="cloud/gemini-2.5-flash-tts")
ok(calls == [("မင်္ဂလာပါ", "Kore", "cloud/gemini-2.5-flash-tts")] and os.path.exists(f"{tmp}/a.wav"), "synthesize_to_file routes cloud/ models to Cloud TTS")

# director's notes become the Cloud `prompt`, never part of the spoken text
style, spoken = cloud_tts.split_notes(compose_emotion("fearfully", "မလုပ်ပါနဲ့!"))
ok(style == "Style: speak fearfully." and spoken == "မလုပ်ပါနဲ့!" and "notes" not in (style or "").lower(), f"notes split: {style!r} / {spoken!r}")
ok(cloud_tts.split_notes("plain text") == (None, "plain text"), "plain text has no prompt")

# the request body and error mapping (HTTP mocked)
sent = {}
class R:
    def __init__(self, code, body): self.status_code, self._b, self.text = code, body, json.dumps(body)
    def json(self): return self._b
import requests  # noqa: E402
import importlib  # noqa: E402
importlib.reload(cloud_tts)
cloud_tts._token = lambda: "tok"
def fake_post(url, json=None, headers=None, timeout=None):
    sent.update(url=url, body=json, headers=headers)
    return R(200, {"audioContent": "UklGRg=="})
requests.post = fake_post
cloud_tts.synthesize(compose_emotion("sadly", "စာသား"), f"{tmp}/b.wav", "Charon", "cloud/gemini-2.5-pro-tts")
b = sent["body"]
ok(b["voice"] == {"languageCode": "my-MM", "name": "Charon", "modelName": "gemini-2.5-pro-tts"} and b["input"] == {"text": "စာသား", "prompt": "Style: speak sadly."}, "request body: voice, model and prompt")
ok(sent["headers"]["x-goog-user-project"] == "demo-project" and os.path.getsize(f"{tmp}/b.wav") > 0, "billing project header + file written")
requests.post = lambda *a, **k: R(429, {"error": {"message": "Quota exceeded"}})
try:
    cloud_tts.synthesize("x", f"{tmp}/c.wav", "Kore", "cloud/gemini-2.5-flash-tts")
    ok(False, "429 should raise")
except RuntimeError as e:
    ok(str(e).startswith("429") , "HTTP 429 raised with the status first (the pool's retry logic reads it)")

# off switch + not configured
os.environ["CLOUD_TTS"] = "0"
ok([m for m, _, _ in tts_pool.models()] == ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"], "CLOUD_TTS=0 removes Cloud from the pool")
os.environ["CLOUD_TTS"] = "1"; os.environ["GCP_PROJECT_ID"] = ""
ok(not cloud_tts.enabled() and not any(m.startswith("cloud/") for m, _, _ in tts_pool.models()), "no project id -> not in the pool")
print("ALL OK")
