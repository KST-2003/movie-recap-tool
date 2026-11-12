"""Offline: a failed voice batch is retried as two halves (a few requests) instead of one request per line, and Gemini's
"audio stream could not be completed" answer counts as a temporary error. Run: python test_bulk_halve.py"""
import os, tempfile, wave
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db",
                  TTS_PROVIDER="fake", TTS_BULK="1")
import pipeline, bulk_tts, gemini_tts  # noqa: E402

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

def tone(path, secs=1.0):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\x00\x00" * int(24000 * secs))

N, BAD = 12, 7
texts = [f"စာကြောင်း နံပါတ် {i} ဖြစ်ပါတယ်။" for i in range(N)]
paths = [f"{tmp}/c{i}.wav" for i in range(N)]
calls = {"batch": [], "single": []}

def fake_batch(group_texts, voice, group_paths, one, out_dir, model):
    calls["batch"].append(len(group_texts))
    if texts[BAD] in group_texts:
        raise RuntimeError("Gemini TTS failed: Error code: 400 - The audio stream could not be completed.")
    for p in group_paths: tone(p)
    return True

def fake_single(text, voice, path, chooser=None, style=None, **kw):
    calls["single"].append(text); tone(path); return 1.0

bulk_tts.synthesize_batch = fake_batch
pipeline.synthesize = fake_single
pipeline.plan_batches = lambda t, v, s: [list(range(len(t)))]
pipeline.check_cancelled = lambda j: None
pipeline.storage.put_clip = lambda *a, **k: None
durs = pipeline.voice_many(texts, paths, "Kore", {}, "job")
total = len(calls["batch"]) + len(calls["single"])
ok(all(d > 0 for d in durs) and all(os.path.exists(p) for p in paths), "every line has a clip")
ok(calls["batch"][:3] == [12, 6, 6] or calls["batch"][0] == 12, f"batch sizes tried: {calls['batch']}")
ok(len(calls["single"]) <= 3 and texts[BAD] in calls["single"], f"only the small group around the bad line went one by one ({len(calls['single'])} lines)")
ok(total <= 8, f"{total} requests in all (was 13: the batch + one per line)")

src = open(gemini_tts.__file__).read()
ok('"could not be completed"' in src.split("transient = any(")[1][:400], "'could not be completed' is retried like a busy answer")
print("ALL OK")
