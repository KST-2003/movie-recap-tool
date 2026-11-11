"""Offline test: 3 failed/cancelled videos that already cost tokens within 5 h -> new uploads refused until the oldest leaves the window.
Run: python test_fail_lockout.py"""
import os, subprocess, tempfile
from datetime import timedelta
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DATABASE_URL=f"sqlite:///{tmp}/t.db", ALLOW_SIGNUP="true")
from fastapi.testclient import TestClient
import db
from main import app

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

c = TestClient(app)
tok = c.post("/api/auth/register", json={"email": "f@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
with db.Session() as s:
    uid = s.query(db.User).filter_by(email="f@example.com").one().id
def add(status, hours_ago, usage):
    with db.Session() as s:
        s.add(db.Job(id=os.urandom(6).hex(), user_id=uid, status=status, params={}, data={"usage": usage} if usage else {}, charged_seconds=0.0,
                     finished_at=db.utcnow() - timedelta(hours=hours_ago), input_key="x"))
        s.commit()
def wait():
    with db.Session() as s: return db.failure_wait_seconds(s, uid)
for h in (6, 5, 4, 3): add("error", h, None)
ok(wait() == 0, "4 failures in a row: still free")
add("done", 2.5, {"gemini": 5})
add("cancelled", 2, None)
ok(wait() == 0, "a finished video resets the run")
for h in (1.5, 1.2, 1.0): add("error", h, None)
ok(wait() == 0, "only 4 failures since the last success: free")
add("cancelled", 1.0 / 6, None)   # 10 minutes ago = the 5th in a row
w = wait()
ok(2.7 * 3600 < w < 2.9 * 3600, f"5 in a row: blocked until 3 h after the last one = {w/60:.0f} min")
video = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=10:d=2", "-pix_fmt", "yuv420p", video], check=True)
with open(video, "rb") as f:
    r = c.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")}, data={"voice_type": "su"})
ok(r.status_code == 429 and "Too many videos failed" in r.json()["detail"], f"upload refused: {r.json()['detail']}")
add("done", 0, {"gemini": 5})
ok(wait() == 0, "a finished video resets it")
print("ALL OK")
