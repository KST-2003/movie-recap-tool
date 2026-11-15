"""Offline: a device-made video is uploaded to the server and then opens from "My videos". Run: venv/bin/python test_device_video.py"""
import os, subprocess, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db", TTS_PROVIDER="fake",
                  DUB_PROVIDER="fake", ALLOW_SIGNUP="true", REDIS_URL="", STORAGE_BACKEND="local", DEVICE_VIDEO_MAX_MB="5")
for d in ("data", "up", "out"): os.makedirs(f"{tmp}/{d}")
from fastapi.testclient import TestClient
import main, config
from db import Job, Session, User
bad = 0
def ok(c, what):
    global bad
    print(("ok   " if c else "FAIL ") + what); bad += 0 if c else 1
def clip(path, seconds, codec="libx264"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={seconds}", "-c:v", codec, "-pix_fmt", "yuv420p", path], check=True)
ok(config.KEEP_RESULT_DAYS == 14 and config.KEEP_SOURCE_DAYS == 14, "both keeping times default to 14 days")
c = TestClient(main.app)
def user(name):
    r = c.post("/api/auth/register", json={"email": name, "password": "password123"})
    return {"Authorization": "Bearer " + r.json()["token"]}
a, b = user("a@example.com"), user("b@example.com")
src = f"{tmp}/up/src.mp4"; clip(src, 2)
open(f"{tmp}/out/j1_voice.m4a", "wb").write(b"x"); open(f"{tmp}/out/j1.srt", "w").write("1\n")
with Session() as s:
    uid = s.query(User).filter_by(email="a@example.com").one().id
    res = {"device_plan": {"duration": 6.0, "speed": 1.0, "out": [160, 90]}, "audio_file": "j1_voice.m4a", "subtitle_file": "j1.srt", "timeline": [], "project": {"segments": []}}
    s.add(Job(id="j1", user_id=uid, status="done", stage="Done", progress=100, params={"device_render": True}, input_key=src, data={"result": res}))
    s.add(Job(id="j2", user_id=uid, status="done", stage="Done", progress=100, params={}, input_key=src, data={"result": {"video_file": "none.mp4", "timeline": []}}))
    s.commit()
row = lambda: next(i for i in c.get("/api/jobs", headers=a).json()["items"] if i["id"] == "j1")
ok(row()["device"] and not row()["video_available"] and row()["editable"], "before the upload: device video, not on the server, editable")
good, short, notvid, wrong = f"{tmp}/good.mp4", f"{tmp}/short.mp4", f"{tmp}/x.mp4", f"{tmp}/w.mp4"
clip(good, 6); clip(short, 2); open(notvid, "wb").write(b"hello" * 100); clip(wrong, 6, "mpeg4")
up = lambda path, h, job="j1": c.post(f"/api/jobs/{job}/device-video", headers=h, files={"video": ("v.mp4", open(path, "rb"), "video/mp4")})
ok(up(good, b).status_code == 404, "another user cannot upload to the job")
ok(up(good, a, "j2").status_code == 409, "a server-rendered job takes no upload")
ok(up(short, a).status_code == 400, "a video of the wrong length is refused")
ok(up(notvid, a).status_code == 400, "a file that is not a video is refused")
ok(up(wrong, a).status_code == 400, "a video that is not H.264 is refused")
ok(sorted(os.listdir(f"{tmp}/out")) == ["j1.srt", "j1_voice.m4a"], "refused uploads leave no file")
ok(up(good, a).status_code == 200 and os.path.exists(f"{tmp}/out/recap_output_j1.mp4"), "the finished video is stored")
r = c.get("/api/jobs/j1", headers=a).json()["result"]
ok(bool(r.get("video_url")) and bool(r.get("download_url")) and bool(r.get("audio_url")) and r.get("device_plan") and not r.get("expired"), "the job now has video links and keeps its plan + sound")
ok(c.get(r["video_url"]).status_code == 200, "the video link works")
ok(row()["video_available"] and row()["can_edit"] and row()["expires_at"], "My videos: available, editable, with an end date")
os.remove(f"{tmp}/out/j1_voice.m4a")
r = c.get("/api/jobs/j1", headers=a).json()["result"]
ok(r.get("video_url") and not r.get("expired"), "still opens when the sound file is gone")
ok(c.delete("/api/jobs/j1", headers=a).status_code == 200 and not os.path.exists(f"{tmp}/out/recap_output_j1.mp4"), "deleting the video removes the uploaded copy")
ok(up(good, a).status_code in (404, 409), "no upload to a deleted video")
big = f"{tmp}/big.mp4"; open(big, "wb").write(b"0" * (6 * 1024 * 1024))
with Session() as s:
    s.add(Job(id="j3", user_id=uid, status="done", stage="Done", progress=100, params={}, input_key=src, data={"result": res})); s.commit()
ok(up(big, a, "j3").status_code == 413, "a file over the size limit is refused")
print("ALL OK" if not bad else f"{bad} FAILED"); sys.exit(1 if bad else 0)
