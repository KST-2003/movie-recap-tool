"""Offline: a Standard (Azure) video's voice clips must be found again by an editor re-render (it re-voiced all 171 lines: 0 from cache),
and Standard clips of different Gemini voice names with the same Azure voice are the same clip. Run: python test_standard_cache.py"""
import os, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db", TTS_PROVIDER="fake")
os.makedirs(f"{tmp}/out", exist_ok=True)
import pipeline, storage, tts_pool, bulk_tts, subprocess  # noqa: E402

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: raise SystemExit(1)

# a batch (bulk) voice request for an Azure job: clips are cut out of one audio, they never went through gemini_tts
def fake_batch(texts, voice, paths, single, out_dir, model):
    for p in paths:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:d=0.5", "-ar", "24000", "-ac", "1", p], check=True)
    return True
bulk_tts.synthesize_batch = fake_batch
class Chooser:
    def get(self): return "azure/neural"
texts = ["မင်္ဂလာပါ။", "ကျေးဇူးတင်ပါတယ်။"]
voices = ["Puck", "Puck"]
paths = [f"{tmp}/out/a{i}.wav" for i in range(2)]
pipeline.voice_many(texts, paths, voices, {"a": 0.13, "b": 0.7}, "j", None, Chooser(), [None, None])
for t, v in zip(texts, voices):
    dest = f"{tmp}/got.wav"
    hit = storage.fetch_clip(pipeline.clip_name(t, pipeline.clip_voice(v, model="azure/neural")), dest)   # what the editor re-render asks for
    ok(hit, f"re-render finds the cached Standard clip for '{t}'")
    ok(storage.fetch_clip(pipeline.clip_name(t, pipeline.clip_voice("Charon", model="azure/neural")), dest), "another male voice name maps to the same Azure clip")
    ok(not storage.fetch_clip(pipeline.clip_name(t, pipeline.clip_voice("Kore", model="azure/neural")), dest), "the female voice is a different clip")
    ok(not storage.fetch_clip(pipeline.clip_name(t, pipeline.clip_voice(v, model="gemini-3.8-flash-tts")), dest), "a Gemini clip never matches a Standard clip")
print("ALL OK")
