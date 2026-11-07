"""Timing of everything that runs on OUR machine for a 10-minute vertical video (no Gemini calls: fake transcript,
fake voice). The real run adds Gemini time on top; this is the floor. Run: python bench_10min.py [minutes]"""
import os
import re
import subprocess
import sys
import tempfile
import time

MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DUB_PROVIDER="gemini", TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", MAX_VIDEO_MINUTES="30",
                  DEFAULT_DAILY_MINUTES="1000")

from fastapi.testclient import TestClient  # noqa: E402

import gemini_dub  # noqa: E402
from main import app  # noqa: E402

video = f"{tmp}/in.mp4"
secs = int(MIN * 60)
t0 = time.time()
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=720x1280:r=30:d={secs}",
                "-f", "lavfi", "-i", f"sine=frequency=300:duration={secs}", "-c:v", "libx264", "-preset", "ultrafast",
                "-b:v", "3M", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
print(f"made {secs}s test video in {time.time() - t0:.0f}s ({os.path.getsize(video) / 1e6:.0f} MB)", flush=True)

TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။ ဒီဇာတ်လမ်းက စိတ်ဝင်စားစရာကောင်းပါတယ်။"
n = int(secs / 4.0)  # one line per ~4 s, like a recap


def fake_dub(path, target, **kw):
    segs = [{"start": i * 4.0, "end": i * 4.0 + 3.6, "source_text": "x", "translated_text": TEXT} for i in range(n)]
    return "zh", gemini_dub.finish_segments(segs, kw.get("scene_cuts") or [])


gemini_dub.dub = fake_dub
client = TestClient(app)
tok = client.post("/api/auth/register", json={"email": "b@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
start = time.time()
with open(video, "rb") as f:
    r = client.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
                    data={"voice_type": "su", "fit_translation": "false"})
job_id = r.json()["job_id"]
while True:
    j = client.get(f"/api/jobs/{job_id}", headers=H).json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(2)
print(f"\nstatus {j['status']} {j.get('error') or ''} | total {time.time() - start:.0f}s for a {secs}s video "
      f"({(time.time() - start) / secs:.2f}x real time)", flush=True)
