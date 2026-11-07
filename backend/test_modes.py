"""Offline test of full-movie mode, subtitles-only mode, casting, emotions, background audio, soft music, caption size.
No Gemini calls (fake transcript, fake voice). Run: python test_modes.py   (needs ffmpeg)"""
import json
import os
import subprocess
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DUB_PROVIDER="gemini", TTS_BULK="1", DATABASE_URL=f"sqlite:///{tmp}/t.db", RECAP_WORKERS="2",
                  MAX_ACTIVE_JOBS_PER_USER="5")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import casting  # noqa: E402
import gemini_dub  # noqa: E402
import pipeline  # noqa: E402
import recap_engine  # noqa: E402
from main import app  # noqa: E402

# --- unit: batches, casting, caption size, source timing
texts = ["a ဟိုဟိုဟို။", "b ဟိုဟိုဟို။", "c ဟိုဟိုဟို။", "d ဟိုဟိုဟို။"]
batches = pipeline.plan_batches(texts, ["Puck", "Kore", "Puck", "Puck"], [None, None, None, "angrily"])
assert sorted(map(sorted, batches)) == [[0, 2], [1], [3]], batches   # same voice shares a request; styled line alone
segs = [{"speaker": "A", "gender": "male"}] * 4 + [{"speaker": "B", "gender": "female"}] * 2
cast = casting.assign_voices([dict(s) for s in segs], "su")
assert cast["A"]["voice"] != cast["B"]["voice"] and cast["A"]["voice"] in casting.V.MALE and cast["B"]["voice"] in casting.V.FEMALE, cast
big, small = f"{tmp}/big.png", f"{tmp}/small.png"
recap_engine.render_caption("မင်္ဂလာပါ ဒီနေ့ အဆင်ပြေလား", big, 1080, 240, size_px=70)
recap_engine.render_caption("မင်္ဂလာပါ ဒီနေ့ အဆင်ပြေလား", small, 1080, 240, size_px=40)
hb, hs = Image.open(big).getbbox(), Image.open(small).getbbox()
assert (hb[3] - hb[1]) > (hs[3] - hs[1]) * 1.3, (hb, hs)
print("units ok: batches, casting", {k: v["voice"] for k, v in cast.items()}, "caption size follows size_px")

# --- refused audio: halves are retried, a still-refused part is skipped (job survives)
audio = f"{tmp}/a.mp3"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=60", audio], check=True)
real_piece = gemini_dub._dub_piece
tried = []


def fake_piece(path, offset, target, attempts, cuts=None, mode="recap", chunk_no=0, roster=None):
    length = gemini_dub._duration(path)
    tried.append((round(offset), round(length)))
    if length > 50 or (offset >= 30 and length < 40):   # whole piece refused; second half refused too
        raise gemini_dub._Blocked("empty answer from Gemini (reason: OTHER)")
    return "zh", [{"start": offset, "end": offset + 1, "source_text": "x", "translated_text": "y"}]


gemini_dub._dub_piece = fake_piece
skipped = []
lang, segs = gemini_dub._dub_chunk(audio, 0.0, "Burmese", 1, [], "recap", 0, 0, skipped)
gemini_dub._dub_piece = real_piece
assert tried[0] == (0, 60) and (0, 30) in tried and (30, 30) in tried, tried
assert len(segs) == 1 and segs[0]["start"] == 0, segs
assert abs(sum(b - a for a, b in skipped) - 30) < 0.2 and min(a for a, _ in skipped) > 29.9, skipped
print("refused audio ok: split in halves, first half kept, second half skipped and reported", skipped)

# --- voice service refuses a text (content_blocked): ladder = no emotion -> other model -> milder wording -> silent line
import gemini_tts  # noqa: E402
import fit_text  # noqa: E402
import tts_pool  # noqa: E402

ch = tts_pool.Chooser(5)
job_model = ch.get()
attempts_log = []


def fake_tts(text, path, voice=None, retries=3, model=None):
    attempts_log.append((model, text))
    blocked = (("BADSTYLE" in text and text.startswith("Say "))
               or ("BADMODEL" in text and model == job_model)
               or ("BADSOFT" in text)
               or ("BADALL" in text))
    if blocked:
        raise gemini_tts.ContentBlocked("content_blocked")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", path], check=True)


real_stf, real_tp, real_soften = gemini_tts.synthesize_to_file, pipeline.tts_provider, fit_text.soften
gemini_tts.synthesize_to_file, pipeline.tts_provider = fake_tts, (lambda: "gemini")
fit_text.soften = lambda text, lang: text.replace("BADSOFT", "mild") if "BADSOFT" in text else text
out = f"{tmp}/blk.wav"
for text, style in (("BADSTYLE line", "angrily"), ("BADMODEL line", None), ("BADSOFT line", None)):
    attempts_log.clear()
    pipeline.synthesize(text, "Puck", out, ch, style)
    print("  ladder:", text, "->", [(m.split("-")[1] + "-" + m.split("-")[2], t[:18]) for m, t in attempts_log])
assert ch.get() == job_model, "the job keeps its own model; the other model was used for one line only"
try:
    pipeline.synthesize("BADALL line", "Puck", out, ch, None)
    raise AssertionError("must raise LineBlocked")
except pipeline.LineBlocked:
    pass
try:
    pipeline.synthesize("BADALL line", "Puck", out, ch, None, ladder=False)
    raise AssertionError("a group must fail fast")
except gemini_tts.ContentBlocked:
    pass
blocked_list = []
paths = [f"{tmp}/b0.wav", f"{tmp}/b1.wav"]
durs = pipeline.voice_many(["fine line", "BADALL line"], paths, "Puck", dict(duration_model_default := {"a": 0.16, "b": 0.7}),
                           "none", None, ch, None, blocked_list)
assert blocked_list == [1] and durs[1] >= 0.8 and os.path.getsize(paths[1]) > 0, (blocked_list, durs)
gemini_tts.synthesize_to_file, pipeline.tts_provider, fit_text.soften = real_stf, real_tp, real_soften
print("refusal ladder ok: emotion dropped, other model, milder wording, then a silent line instead of a failed job")

# --- an 18 s video with a tone
video = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=18",
                "-f", "lavfi", "-i", "sine=frequency=300:duration=18", "-pix_fmt", "yuv420p", "-shortest", video], check=True)

TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
fake = [{"start": 0.0, "end": 3.0, "source_text": "a", "translated_text": TEXT, "speaker": "A", "gender": "male", "emotion": "angry"},
        {"start": 3.0, "end": 6.0, "source_text": "b", "translated_text": TEXT, "speaker": "B", "gender": "female", "emotion": "neutral"},
        {"start": 6.0, "end": 9.0, "source_text": "c", "translated_text": TEXT, "speaker": "A", "gender": "male", "emotion": "neutral"},
        {"start": 9.0, "end": 12.0, "source_text": "d", "translated_text": TEXT, "speaker": "B", "gender": "female", "emotion": "sad"},
        {"start": 12.0, "end": 18.0, "source_text": "e", "translated_text": TEXT, "speaker": "A", "gender": "male", "emotion": "neutral"}]
seen_modes = []


def fake_dub(path, target, **kw):
    seen_modes.append(kw.get("mode"))
    return "zh", gemini_dub.finish_segments([dict(s) for s in fake], [])


gemini_dub.dub = fake_dub
calls = []
real_synth = pipeline.synthesize
pipeline.synthesize = lambda text, voice, path, chooser=None, style=None, ladder=True: (calls.append((voice, style)), real_synth(text, voice, path))[1]
real_provider = pipeline.tts_provider

client = TestClient(app)
tok = client.post("/api/auth/register", json={"email": "m@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}


def wait(job_id):
    for _ in range(240):
        j = client.get(f"/api/jobs/{job_id}", headers=H).json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(1)
    raise TimeoutError


def submit(**data):
    base = {"voice_type": "su", "fit_translation": "false", "enable_flip": "false", "blur_subtitles": "false",
            "remove_watermark": "false"}
    base.update(data)
    with open(video, "rb") as f:
        r = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")}, data=base)
    assert r.status_code == 200, r.text
    return wait(r.json()["job_id"])


def streams(job):
    path = os.path.join(os.environ["OUTPUT_DIR"], f"recap_output_{job['id']}.mp4")
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-show_entries", "format=duration",
                          "-of", "json", path], capture_output=True, text=True).stdout
    d = json.loads(out)
    return [s["codec_type"] for s in d["streams"]], float(d["format"]["duration"])


# 1. validation
bad = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", open(video, "rb"), "video/mp4")}, data={"mode": "nonsense"})
assert bad.status_code == 400, bad.text

# 2. full movie: characters, fixed voices, emotions, original sound ducked under the voice, soft music
job = submit(mode="full", background="original", soft_music="true")
assert job["status"] == "done", job.get("error")
assert seen_modes == ["full"], seen_modes
proj = job["result"]["project"]
sp = proj["speakers"]
assert set(sp) == {"A", "B"} and sp["A"]["voice"] != sp["B"]["voice"], sp
by_speaker = {}
for sg, s in zip(proj["segments"], fake):
    assert sg["speaker"] == s["speaker"]
voices_used = {v for v, _ in calls}
assert voices_used == {sp["A"]["voice"], sp["B"]["voice"]}, (voices_used, sp)
assert sorted(st for _, st in calls if st) == ["angrily", "sadly"], calls   # only the two emotional lines carry a direction
kinds, dur = streams(job)
assert "audio" in kinds and "video" in kinds and dur > 17, (kinds, dur)
assert job["result"]["background_kept"] is True
print("full mode ok:", {k: v["voice"] for k, v in sp.items()}, "requests:", len(calls), "output", round(dur, 1), "s")

# 3. editor: change character B's voice -> only B's lines are voiced again
before = len(calls)
new_voice = "Sulafat" if sp["B"]["voice"] != "Sulafat" else "Aoede"
lines = [{"id": s["id"], "start": s["start"], "text": s["text"]} for s in proj["segments"]]
r = client.post(f"/api/jobs/{job['id']}/rerender", headers=H, json={"segments": lines, "speaker_voices": {"B": new_voice}})
assert r.status_code == 200, r.text
job2 = wait(r.json()["job_id"])
assert job2["status"] == "done", job2.get("error")
p2 = job2["result"]["project"]
assert p2["speakers"]["B"]["voice"] == new_voice and p2["speakers"]["A"]["voice"] == sp["A"]["voice"], p2["speakers"]
new_calls = calls[before:]
assert {v for v, _ in new_calls} == {new_voice}, new_calls   # A's lines come from the clip cache
assert [s["speaker"] for s in p2["segments"]] == [s["speaker"] for s in proj["segments"]], "characters survive an edit"
print("editor character voice change ok:", len(new_calls), "new requests, all for", new_voice)

# 3b. editor: give character B a LOOK (monster): accepted, only B re-voiced, the look id is what is stored and cached
before = len(calls)
r = client.post(f"/api/jobs/{job2['id']}/rerender", headers=H, json={"segments": lines, "speaker_voices": {"B": "look:monster"}})
assert r.status_code == 200, r.text
job2b = wait(r.json()["job_id"])
assert job2b["status"] == "done", job2b.get("error")
assert job2b["result"]["project"]["speakers"]["B"]["voice"] == "look:monster"
assert {v for v, _ in calls[before:]} == {"look:monster"}, calls[before:]
bad = client.post(f"/api/jobs/{job2['id']}/rerender", headers=H, json={"segments": lines, "speaker_voices": {"B": "look:nope"}})
assert bad.status_code == 200 and wait(bad.json()["job_id"])["result"]["project"]["speakers"]["B"]["voice"] == new_voice, "unknown look is ignored"
print("look as character voice ok")

# 4. subtitles only: no voice requests at all, original sound and timing kept
before = len(calls)
job3 = submit(mode="full", output="subtitles")
assert job3["status"] == "done", job3.get("error")
assert len(calls) == before, "subtitles-only must not call the TTS"
kinds, dur = streams(job3)
assert "audio" in kinds and abs(dur - 18.0) < 0.6, (kinds, dur)
sc = job3["result"]["timeline"]
assert all(abs(t["output_length"] - (t["source_end"] - t["source_start"])) < 0.01 for t in sc), "video timing untouched"
assert job3["result"]["project"]["output"] == "subtitles"
print("subtitles-only ok: no voice requests, output", round(dur, 1), "s with original audio")

# 4b. original speech removed (Demucs, faked here): runs once, a re-render of the same video reuses it, failure falls back
sep_calls = []


def fake_separate(video_path, work_dir, tag, timeout=1800):
    sep_calls.append(tag)
    out = os.path.join(work_dir, f"{tag}_fake_bg.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=500:duration=18", out], check=True)
    return out


pipeline.separate_background = fake_separate
job5 = submit(mode="full", background="separate")
assert job5["status"] == "done" and len(sep_calls) == 1 and job5["result"]["background_kept"], (job5.get("error"), sep_calls)
p5 = job5["result"]["project"]
lines = [{"id": s["id"], "start": s["start"], "text": s["text"]} for s in p5["segments"]]
lines[0]["text"] = "စာသားအသစ်။"
r = client.post(f"/api/jobs/{job5['id']}/rerender", headers=H, json={"segments": lines})
job6 = wait(r.json()["job_id"])
assert job6["status"] == "done" and len(sep_calls) == 1, (job6.get("error"), sep_calls)   # cache hit: no second separation
print("separation ok: ran once, re-render reused it")


def broken_separate(*a, **k):
    raise RuntimeError("demucs exploded")


pipeline.separate_background = broken_separate
job7 = submit(mode="full", background="separate")
assert job7["status"] == "done", job7.get("error")
assert any("original" in w for w in job7["result"].get("warnings", [])), job7["result"].get("warnings")
print("separation failure -> original sound lowered under the voice + warning")

# 5. recap mode is unchanged: one voice, no speakers
before = len(calls)
job4 = submit(mode="recap")
assert job4["status"] == "done", job4.get("error")
assert {v for v, _ in calls[before:]} == {"su"} and not job4["result"]["project"]["speakers"]
print("recap mode ok")
print("ALL OK")
sys.exit(0)
