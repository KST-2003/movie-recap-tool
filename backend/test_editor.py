"""Offline end-to-end test of scene cuts + editor re-render. No Gemini calls (fake voice, fake transcript).
Run: python test_editor.py   (needs ffmpeg)"""
import os
import subprocess
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="",
                  DUB_PROVIDER="gemini", TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", RECAP_WORKERS="2", MAX_ACTIVE_JOBS_PER_USER="3")

from fastapi.testclient import TestClient  # noqa: E402

import gemini_dub  # noqa: E402
import pipeline  # noqa: E402
import scene_cuts  # noqa: E402
from main import app  # noqa: E402

# 1. a 18 s video: six 3-second colour blocks (hard cuts at 3, 6, 9, 12, 15) with a tone
video = f"{tmp}/in.mp4"
colours = ["red", "white", "black", "green", "white", "blue"]
cmd = ["ffmpeg", "-y", "-loglevel", "error"]
for c in colours:
    cmd += ["-f", "lavfi", "-i", f"color=c={c}:s=320x240:r=25:d=3"]
cmd += ["-f", "lavfi", "-i", "sine=frequency=300:duration=18"]
cmd += ["-filter_complex", "".join(f"[{i}:v]" for i in range(6)) + "concat=n=6:v=1:a=0[v]", "-map", "[v]", "-map", "6:a",
        "-shortest", "-pix_fmt", "yuv420p", video]
subprocess.run(cmd, check=True)

cuts = scene_cuts.detect_cuts(video)
print("cuts:", cuts)
assert len(cuts) == 5 and all(abs(c - 3 * (i + 1)) < 0.2 for i, c in enumerate(cuts)), cuts
assert scene_cuts.snap(3.2, cuts) == cuts[0] and scene_cuts.snap(4.5, cuts) == 4.5

# 2. fake transcript (slightly off the cuts, one line far too long) -> snapping + flagging
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
fake = [{"start": 0.1, "end": 3.2, "source_text": "a", "translated_text": TEXT},
        {"start": 3.2, "end": 5.9, "source_text": "b", "translated_text": " ".join([TEXT] * 5)},
        {"start": 6.1, "end": 9.0, "source_text": "c", "translated_text": TEXT},
        {"start": 9.0, "end": 18.0, "source_text": "d", "translated_text": " ".join([TEXT] * 2)}]
seen = {}


def fake_dub(path, target, **kw):
    seen["cuts"] = kw.get("scene_cuts")
    return "zh", gemini_dub.finish_segments([dict(s) for s in fake], kw.get("scene_cuts") or [])


gemini_dub.dub = fake_dub
calls = []
real_synth = pipeline.synthesize
pipeline.synthesize = lambda text, voice, path, chooser=None, style=None, ladder=True: (calls.append(text), real_synth(text, voice, path))[1]

client = TestClient(app)
tok = client.post("/api/auth/register", json={"email": "t@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}


def wait(job_id):
    for _ in range(240):
        j = client.get(f"/api/jobs/{job_id}", headers=H).json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(1)
    raise TimeoutError


with open(video, "rb") as f:
    r = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
                    data={"voice_type": "su", "fit_translation": "false", "enable_flip": "false",
                          "blur_subtitles": "false", "remove_watermark": "false"})
assert r.status_code == 200, r.text
job = wait(r.json()["job_id"])
assert job["status"] == "done", job.get("error")
assert seen["cuts"] and len(seen["cuts"]) == 5, "scene cuts must reach the transcriber"
proj = job["result"]["project"]
print("project:", [(s["id"], s["start"], s.get("action"), s["audio_dur"]) for s in proj["segments"]])
assert [s["start"] for s in proj["segments"]] == [0.1, 3.0, 6.0, 9.0], "starts snap to cuts (0.1 is within 0.3 of no cut)"
assert len(calls) == 4, calls

# 3. edit: change line 2 text, slow line 3 (tempo), delete line 4 -> exactly one new voice request
first_calls = len(calls)
lines = [{"start": proj["segments"][0]["start"], "text": proj["segments"][0]["text"]},
         {"start": 3.0, "text": "အသစ်ပြင်ထားသော စာကြောင်း။"},
         {"start": 6.0, "text": proj["segments"][2]["text"], "tempo": 0.9}]
r = client.post(f"/api/jobs/{job['id']}/rerender", headers=H, json={"segments": lines})
assert r.status_code == 200, r.text
job2 = wait(r.json()["job_id"])
assert job2["status"] == "done", job2.get("error")
assert len(calls) - first_calls == 1, f"only the edited line may be re-voiced, got {calls[first_calls:]}"
p2 = job2["result"]["project"]
assert len(p2["segments"]) == 3 and p2["segments"][2]["tempo"] == 0.9 and abs(p2["segments"][2]["applied_tempo"] - 0.9) < 0.01
print("edit job output:", job2["result"]["output_duration"], "s; voice requests for edit:", len(calls) - first_calls)

# 3b. script fitting: too-long line is shortened, too-short line is lengthened (LLM calls faked), voice speed untouched
pipeline.fit_available = lambda: True
rewrite_calls = []


def fake_rewrite(items, lang):  # ONE call for all lines that need fitting
    rewrite_calls.append(len(items))
    return {it["id"]: (it["current"][: len(it["current"]) // 2] if it["mode"] == "shorten" else it["current"] + " အမှန်ပါ")
            for it in items}


pipeline.fit_text.rewrite_many = fake_rewrite
with open(video, "rb") as f:
    r = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
                    data={"voice_type": "su", "fit_translation": "true", "enable_flip": "false",
                          "blur_subtitles": "false", "remove_watermark": "false"})
job3 = wait(r.json()["job_id"])
assert job3["status"] == "done", job3.get("error")
s3 = job3["result"]["project"]["segments"]
print("rewrite requests (lines each):", rewrite_calls)
assert len(rewrite_calls) <= 8 and max(rewrite_calls) >= 3, "lines must be rewritten in bulk, not one request per line"
print("fitted durations:", [(s["id"], s["audio_dur"], s.get("slot")) for s in s3])
assert s3[2]["audio_dur"] > proj["segments"][2]["audio_dur"] + 0.3, "short line must be lengthened"
assert s3[1]["audio_dur"] < proj["segments"][1]["audio_dur"] / 2, "long line must be shortened"
assert all(s["applied_tempo"] <= 1.05 for s in s3[1:3]), "no voice speed-up needed after fitting"

# 3c. time budget: with no time left the optional fitting is skipped, the job still finishes
before = len(rewrite_calls)
pipeline.JOB_BUDGET_MAX = 1.0
with open(video, "rb") as f:
    r = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
                    data={"voice_type": "su", "fit_translation": "true", "enable_flip": "false",
                          "blur_subtitles": "false", "remove_watermark": "false"})
job4 = wait(r.json()["job_id"])
assert job4["status"] == "done", job4.get("error")
assert len(rewrite_calls) == before, "fitting must be skipped when the time budget is used up"
print("budget exhausted: fitting skipped, job done")
pipeline.JOB_BUDGET_MAX = 540.0

# 3d. TTS model pool: preference order, per-model blocks, switching, per-minute limiter
import gemini_tts  # noqa: E402
import tts_pool  # noqa: E402

names = [m for m, _, _ in tts_pool.models()]
assert names[0] == "gemini-3.1-flash-tts-preview" and names[-1] == "gemini-2.5-pro-preview-tts"
ch = tts_pool.Chooser(10)
assert ch.get() == names[0], ch.get()
assert tts_pool.Chooser(10, preferred=names[1]).get() == names[1], "a job's earlier model is preferred (edits keep the voice)"
gemini_tts._block("limit. retry in 23h59m59s", names[0])
assert gemini_tts.blocked_for(names[0]) > 80000 and gemini_tts.blocked_for(names[1]) == 0, "blocks are per model"
assert tts_pool.Chooser(10).get() == names[1], "a blocked model is skipped"
for n in names:
    gemini_tts._block("retry in 1h", n)
assert tts_pool.all_blocked()
try:
    tts_pool.Chooser(1)
    raise AssertionError("must raise when every model is blocked")
except gemini_tts.QuotaExceeded as e:
    print("all blocked ->", str(e)[:80])
open(gemini_tts.BLOCK_FILE, "w").write("{}")   # unblock everything
# pipeline.synthesize switches model on QuotaExceeded
ch = tts_pool.Chooser(1)
first, seen_models = ch.get(), []


def fake_tts(text, path, voice=None, retries=3, model=None):
    seen_models.append(model)
    if model == first:
        raise gemini_tts.QuotaExceeded("daily limit")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", path], check=True)


real_tts_provider, real_stf = pipeline.tts_provider, gemini_tts.synthesize_to_file
pipeline.tts_provider = lambda: "gemini"
gemini_tts.synthesize_to_file = fake_tts
real_synth("မင်္ဂလာပါ။", "su", f"{tmp}/sw.wav", ch)  # the real function (pipeline.synthesize is wrapped by the call counter)
pipeline.tts_provider, gemini_tts.synthesize_to_file = real_tts_provider, real_stf
assert seen_models[0] == first and seen_models[-1] != first and ch.get() != first, (first, seen_models, ch.get())
print("model switch ok:", seen_models)
# limiter: 2 requests per 1 s window (SAFETY 0) -> the 3rd waits for the window
tts_pool.WINDOW, tts_pool.SAFETY = 1.0, 0
tts_pool.DEFAULT_MODELS[:] = [("m-test", 2, 100)]
t_start = time.time()
for _ in range(3):
    tts_pool.acquire("m-test")
assert time.time() - t_start >= 0.9, "per-minute limiter must delay the 3rd request"
print("limiter ok")

# 3e. single-line preview: one voice request, cached so Apply does not pay again
n_before = len(calls)
r = client.post(f"/api/jobs/{job['id']}/preview-line", headers=H, json={"id": proj["segments"][0]["id"], "text": "ဒီမှာ စမ်းကြည့်မယ်။", "voice": "Kore"})
assert r.status_code == 200 and len(r.content) > 1000, r.status_code
assert client.post(f"/api/jobs/{job['id']}/preview-line", headers=H, json={"text": "x", "voice": "Nope"}).status_code == 400
print("preview ok", len(r.content), "bytes")

# 4. validation + queue ETA
bad = client.post(f"/api/jobs/{job['id']}/rerender", headers=H, json={"segments": [{"start": 999, "text": "x"}]})
assert bad.status_code == 400, bad.text
from db import Job, Session  # noqa: E402
with Session() as s:
    s.add(Job(id="queuedjob0001", user_id=1, status="queued", params={}, data={}, input_key="x"))
    s.commit()
q = client.get("/api/jobs/queuedjob0001", headers=H).json()
print("queued view:", {k: q[k] for k in ("status", "queue_position", "eta_seconds")})
assert q["queue_position"] == 1 and q["eta_seconds"] == 0
# 5. cancel: a queued job is cancelled, and the worker then refuses to run it
c = client.post("/api/jobs/queuedjob0001/cancel", headers=H).json()
assert c["status"] == "cancelled", c
pipeline.run_job_by_id("queuedjob0001")
assert client.get("/api/jobs/queuedjob0001", headers=H).json()["status"] == "cancelled"
print("ALL OK")
sys.exit(0)
