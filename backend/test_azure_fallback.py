"""Offline test: Azure Neural TTS as the last fallback for RECAP videos (no request is sent). Run: python test_azure_fallback.py"""
import json
import os
import re
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", AZURE_SPEECH_KEY="k-test", AZURE_SPEECH_REGION="southeastasia", AZURE_TTS="1",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", TTS_MODELS="a1:10:100,a2:10:100", DATABASE_URL=f"sqlite:///{tmp}/t.db")

import azure_tts  # noqa: E402
import gemini_tts  # noqa: E402
import pipeline  # noqa: E402
import tts_pool  # noqa: E402
import usage  # noqa: E402
from looks import compose_emotion  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


names = [m for m, _, _ in tts_pool.models()]
ok(names == ["a1", "a2", "azure/neural"], f"Azure is the last model in the pool: {names}")
ok(dict((m, (a, b)) for m, a, b in tts_pool.models())["azure/neural"] == (120, 100000), "soft limits 120/min, 100000/day")

# recap only
ok(tts_pool.usable("azure/neural", "recap") and not tts_pool.usable("azure/neural", "full") and not tts_pool.usable("azure/neural", None) and tts_pool.usable("a1", "full"), "Azure usable for recap only")
os.makedirs(f"{tmp}/data", exist_ok=True)
json.dump({"day": tts_pool._today(), "counts": {"a1": 100, "a2": 100}}, open(tts_pool.USAGE_FILE, "w"))
ok(tts_pool.admit(60, "recap") == "azure/neural", "AI Studio used up: a recap video is admitted on Azure")
ok(tts_pool.admit(60, "full") is None and tts_pool.admit(60, None) is None, "a full movie is NOT admitted on Azure (busy instead)")
ch = tts_pool.Chooser(10, mode="recap")
ok(ch.get() == "azure/neural" and "azure/neural" in ch.models_used, "recap Chooser picks Azure")
try:
    tts_pool.Chooser(10, mode="full")
    ok(False, "full mode must not get Azure")
except gemini_tts.QuotaExceeded:
    ok(True, "full mode: no model left -> QuotaExceeded (never Azure)")
json.dump({"day": tts_pool._today(), "counts": {}}, open(tts_pool.USAGE_FILE, "w"))
ch = tts_pool.Chooser(10, mode="recap")
gemini_tts._block("quota exceeded retry in 5h", "a1"); gemini_tts._block("quota exceeded retry in 5h", "a2")
ch.failed("a1")
ok(ch.get() == "azure/neural" and ch.switches == [("a1", "azure/neural")] and ch.models_used == {"a1", "azure/neural"}, "mid-video: recap switches to Azure and records it")

# voice mapping + SSML
ok(azure_tts.azure_voice("Kore") == "my-MM-NilarNeural" and azure_tts.azure_voice("Charon") == "my-MM-ThihaNeural"
   and azure_tts.azure_voice(None) == "my-MM-NilarNeural" and azure_tts.azure_voice("su") == "my-MM-NilarNeural", "Gemini voice -> Azure voice by gender")
ssml = azure_tts.build_ssml("a & b <c>", "my-MM-ThihaNeural")
ok("a &amp; b &lt;c&gt;" in ssml and 'name="my-MM-ThihaNeural"' in ssml and 'xml:lang="my-MM"' in ssml, "SSML escapes & < >")

# the request (HTTP mocked): notes are dropped, only the spoken text is sent, key + region used, characters counted
import requests  # noqa: E402
sent = {}
class R:
    def __init__(self, code, content=b"RIFFxxxx"): self.status_code, self.content, self.text = code, content, "x"
def fake_post(url, data=None, headers=None, timeout=None):
    sent.update(url=url, data=data.decode(), headers=headers)
    return R(200)
requests.post = fake_post
usage.start("jz")
gemini_tts.synthesize_to_file(compose_emotion("fearfully", "မလုပ်ပါနဲ့!"), f"{tmp}/a.wav", "Charon", model="azure/neural")
ok(sent["url"] == "https://southeastasia.tts.speech.microsoft.com/cognitiveservices/v1" and sent["headers"]["Ocp-Apim-Subscription-Key"] == "k-test", "request goes to the region's endpoint with the key")
ok("မလုပ်ပါနဲ့!" in sent["data"] and "fearfully" not in sent["data"] and "my-MM-ThihaNeural" in sent["data"], "emotion notes dropped, male voice mapped")
ok(tts_pool.model_of(f"{tmp}/a.wav") == "azure/neural", "the clip is marked as made by Azure")
snap = usage.snapshot("jz")["azure/neural"]
ok(snap["chars"] == len("မလုပ်ပါနဲ့!") and snap["calls"] == 1, f"characters counted: {snap['chars']}")
c = usage.cost_thb({"azure/neural": {"chars": 1000}}, usd_thb=35.0)
ok(abs(c["thb"] - 1000 * 16 / 1e6 * 35) < 1e-9 and c["complete"], f"1000 characters = {c['thb']:.3f} THB at the assumed $16 per 1M")
requests.post = lambda *a, **k: R(429)
try:
    azure_tts.synthesize("x", f"{tmp}/b.wav", "Kore")
    ok(False, "429 should raise")
except RuntimeError as e:
    ok(str(e).startswith("429"), "HTTP 429 raised with the status first (retry logic)")

# cache keys never mix Gemini and Azure clips
ok(pipeline.clip_voice("Kore", model="azure/neural") == "Kore|azure" and pipeline.clip_voice("Kore", model="a1") == "Kore", "Azure clips get their own cache key")
ok(pipeline.clip_name("t", pipeline.clip_voice("Kore", model="azure/neural")) != pipeline.clip_name("t", "Kore"), "different cache names")

# warning text matches the Burmese rule in the frontend
src = open("../frontend/src/i18n.jsx").read()
m = re.search(r"\[/\^(The voice service was busy.*?)\$/,", src)
js = m.group(1).replace("\\(", "(").replace("\\)", ")").replace("\\.", ".")
ok(js == pipeline.VOICE_AZURE_WARNING, "Burmese rule matches the English warning exactly")

# off switches
os.environ["AZURE_TTS"] = "0"
ok("azure/neural" not in [m for m, _, _ in tts_pool.models()], "AZURE_TTS=0 removes it")
os.environ["AZURE_TTS"] = "1"; os.environ["AZURE_SPEECH_KEY"] = ""
ok(not azure_tts.enabled() and "azure/neural" not in [m for m, _, _ in tts_pool.models()], "no key -> not in the pool")
print("ALL OK")
