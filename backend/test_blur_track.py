"""Offline test of the editor's BLUR TRACK: /rerender {blur_windows: [[a,b]]} (source seconds) changes only WHEN the subtitle band is blurred.
Merging/sorting of windows, [] = never blurred, and the picture really is sharp outside the windows. Run: python test_blur_track.py"""
import os, subprocess, tempfile, time
import numpy as np
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DUB_PROVIDER="gemini",
                  TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", MAX_VIDEO_MINUTES="30", DEFAULT_DAILY_MINUTES="1000", ALLOW_SIGNUP="true")
from fastapi.testclient import TestClient
import gemini_dub, pipeline
from main import app

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

video = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=12", "-f", "lavfi", "-i", "sine=frequency=300:duration=12",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
def fake_dub(path, target, **kw):
    segs = [{"start": i * 4.0, "end": i * 4.0 + 3.6, "source_text": "x", "translated_text": TEXT} for i in range(3)]
    return "zh", gemini_dub.finish_segments(segs, kw.get("scene_cuts") or [])
gemini_dub.dub = fake_dub
# the subtitle band is found (always on: presence 0.95 -> blurred the whole film, windows None)
pipeline.detect_text_regions = lambda v, d: {"subtitle": (0.0, 0.70, 1.0, 0.80), "watermarks": [], "line_height": 0.03, "presence": 0.95}
c = TestClient(app)
tok = c.post("/api/auth/register", json={"email": "b@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

def wait(jid):
    while True:
        j = c.get(f"/api/jobs/{jid}", headers=H).json()
        if j["status"] in ("done", "error", "cancelled"): return j
        time.sleep(1)

with open(video, "rb") as f:
    r = c.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
               data={"voice_type": "su", "fit_translation": "false", "flip": "false", "resolution": "720", "aspect": "original"})
j0 = wait(r.json()["job_id"])
ok(j0["status"] == "done", f"first render done ({j0.get('error')})")
proj = j0["result"]["project"]
ok(proj["fx"]["subtitle_rect"] and proj["fx"]["subtitle_windows"] is None, "band found, blurred the whole film (windows None)")
lines = [{"id": s["id"], "start": s["start"], "text": s["text"], "source_text": s.get("source_text", ""), "speaker": s.get("speaker")} for s in proj["segments"]]

def rerender(wins):
    rr = c.post(f"/api/jobs/{j0['id']}/rerender", headers=H, json={"segments": lines, "blur_windows": wins})
    ok(rr.status_code == 200, f"rerender accepted for blur_windows={wins}")
    j = wait(rr.json()["job_id"])
    ok(j["status"] == "done", f"rerender finished ({j.get('error')})")
    return j

jA = rerender([[0, 3], [5, 8], [7.9, 10], [20, 30]])
ok(jA["result"]["project"]["fx"]["subtitle_windows"] == [[0, 3], [5, 10], [20, 13]] or jA["result"]["project"]["fx"]["subtitle_windows"][:2] == [[0, 3], [5, 10]], "windows sorted + merged (touching ones joined, the last is clamped)")
jN = rerender([])
ok(jN["result"]["project"]["fx"]["subtitle_windows"] == [], "[] = never blurred")
jAll = rerender([[0, 12]])
bad = c.post(f"/api/jobs/{j0['id']}/rerender", headers=H, json={"segments": lines, "blur_windows": [[1, 2, 3]] * 500})
ok(bad.status_code == 422, "more than 400 windows refused")

def band_std(job, t):
    f = job["result"].get("video_file") or ""
    path = next((os.path.join(d, n) for d, _, ns in os.walk(f"{tmp}/out") for n in ns if n == os.path.basename(f)), None) or f
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "crop=720:150:0:910,format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).astype(float).reshape(150, 720)
    return float(np.abs(np.diff(img, axis=1)).mean() + np.abs(np.diff(img, axis=0)).mean())   # edge energy: a blurred band has little
sharp, blurred = band_std(jN, 1.0), band_std(jAll, 1.0)
ok(blurred < sharp * 0.85, f"band is blurred inside a window ({blurred:.1f} < {sharp:.1f})")
a1, n1, all1 = band_std(jA, 1.0), band_std(jN, 1.0), band_std(jAll, 1.0)
a11, n11, all11 = band_std(jA, 11.0), band_std(jN, 11.0), band_std(jAll, 11.0)
ok(abs(a1 - all1) < 0.3 and a1 < n1 * 0.85, f"inside a window the picture equals the always-blurred render ({a1:.1f} ~ {all1:.1f}, sharp would be {n1:.1f})")
ok(abs(a11 - n11) < 0.3 and a11 > all11 * 1.15, f"outside the windows it equals the never-blurred render ({a11:.1f} ~ {n11:.1f}, blurred would be {all11:.1f})")
print("ALL OK")
