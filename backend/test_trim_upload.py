"""Offline test: an upload longer than MAX_VIDEO_MINUTES is not refused; only its first minutes are used (cut in place, charged for the
kept part, the result says so); a video within the limit is untouched; an editor re-render does not repeat the notice.
Run: python test_trim_upload.py"""
import os, subprocess, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DUB_PROVIDER="gemini",
                  TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", MAX_VIDEO_MINUTES="0.2", DEFAULT_DAILY_MINUTES="1000", ALLOW_SIGNUP="true")   # limit = 12 s
from fastapi.testclient import TestClient
import gemini_dub
import main
from main import app

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

def make(path, seconds, extra=()):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=360x640:r=30:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p", "-c:a", "aac", *extra, path], check=True)

def length(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path], capture_output=True, text=True).stdout)

# the cutter itself: mp4 and a phone-style mov, cut in place, picture + sound kept
for name in ("a.mp4", "b.mov"):
    p = f"{tmp}/{name}"; make(p, 20)
    got = main.keep_first_seconds(p, 12)
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", p], capture_output=True, text=True).stdout.split()
    ok(abs(got - 12) < 1.2 and abs(length(p) - got) < 0.05 and sorted(streams) == ["audio", "video"], f"{name}: 20 s cut to {got:.2f} s in place, picture + sound kept")
    ok(not [f for f in os.listdir(tmp) if "_cut" in f], f"{name}: no temporary file left")

TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
seen = {}
def fake_dub(path, target, **kw):
    seen["length"] = length(path)
    segs = [{"start": i * 4.0, "end": i * 4.0 + 3.6, "source_text": "x", "translated_text": TEXT} for i in range(int(seen["length"] // 4))]
    return "zh", gemini_dub.finish_segments(segs, kw.get("scene_cuts") or [])
gemini_dub.dub = fake_dub
c = TestClient(app)
tok = c.post("/api/auth/register", json={"email": "t@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

def run(path):
    with open(path, "rb") as f:
        r = c.post("/api/jobs", headers=H, files={"video_file": (os.path.basename(path), f, "video/mp4")}, data={"voice_type": "su", "fit_translation": "false", "resolution": "720"})
    if r.status_code != 200: return r, None
    while True:
        j = c.get(f"/api/jobs/{r.json()['job_id']}", headers=H).json()
        if j["status"] in ("done", "error", "cancelled"): return r, j
        time.sleep(1)

before = c.get("/api/auth/me", headers=H).json()["remaining_seconds"]
long_video = f"{tmp}/long.mp4"; make(long_video, 30)
r, j = run(long_video)
ok(r.status_code == 200 and j and j["status"] == "done", f"30 s upload with a 12 s limit is accepted and finishes ({r.status_code} {j and j.get('error')})")
ok(abs(seen["length"] - 12) < 1.2, f"the pipeline saw only the first part ({seen['length']:.2f} s)")
warns = j["result"].get("warnings") or []
ok(any(w == "This video was 0.5 minutes long, so only the first 0.2 minutes were used." for w in warns), f"the result says it was shortened: {warns}")
used = before - c.get("/api/auth/me", headers=H).json()["remaining_seconds"]
ok(abs(used - seen["length"]) < 1.5, f"charged for the kept part only ({used:.1f} s)")
ok(abs(float(j["result"]["project"]["source_duration"]) - seen["length"]) < 0.5, "the project's source length is the kept part")

segs = [{"id": s["id"], "start": s["start"], "text": s["text"]} for s in j["result"]["project"]["segments"]]
r2 = c.post(f"/api/jobs/{j['id']}/rerender", headers=H, json={"segments": segs})
while True:
    j2 = c.get(f"/api/jobs/{r2.json()['job_id']}", headers=H).json()
    if j2["status"] in ("done", "error", "cancelled"): break
    time.sleep(1)
ok(j2["status"] == "done" and not any("only the first" in w for w in (j2["result"].get("warnings") or [])), "an editor re-render works and does not repeat the notice")

short_video = f"{tmp}/short.mp4"; make(short_video, 10)
r, j = run(short_video)
ok(j and j["status"] == "done" and abs(seen["length"] - 10) < 0.3 and not any("only the first" in w for w in (j["result"].get("warnings") or [])), "a 10 s video (within the limit) is untouched, no notice")

bad = f"{tmp}/bad.mp4"; open(bad, "wb").write(b"not a video")
r, _ = run(bad)
ok(r.status_code == 400, "a broken file is still refused (400)")
print("ALL OK")
