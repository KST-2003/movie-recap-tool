"""Offline test: a job with device_render=true makes only the voice track (m4a) + a render plan, no video; the same job without it
makes the video. A rerender can switch (server fallback). Run: python test_device_plan.py"""
import os, subprocess, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DUB_PROVIDER="gemini",
                  TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", MAX_VIDEO_MINUTES="30", DEFAULT_DAILY_MINUTES="1000", ALLOW_SIGNUP="true")
from fastapi.testclient import TestClient
import gemini_dub
from main import app

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

video = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=12", "-f", "lavfi", "-i", "sine=frequency=300:duration=12",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။ ဒီဇာတ်လမ်းက စိတ်ဝင်စားစရာကောင်းပါတယ်။"
def fake_dub(path, target, **kw):
    segs = [{"start": i * 4.0, "end": i * 4.0 + 3.6, "source_text": "x", "translated_text": TEXT} for i in range(3)]
    return "zh", gemini_dub.finish_segments(segs, kw.get("scene_cuts") or [])
gemini_dub.dub = fake_dub
c = TestClient(app)
tok = c.post("/api/auth/register", json={"email": "d@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}

def wait(jid):
    while True:
        j = c.get(f"/api/jobs/{jid}", headers=H).json()
        if j["status"] in ("done", "error", "cancelled"): return j
        time.sleep(1)

with open(video, "rb") as f:
    r = c.post("/api/jobs", headers=H, files={"video_file": ("in.mp4", f, "video/mp4")},
               data={"voice_type": "su", "fit_translation": "false", "device_render": "true", "flip": "false", "resolution": "720", "aspect": "9:16"})
j = wait(r.json()["job_id"])
ok(j["status"] == "done", f"device job finished ({j.get('error')})")
res = j["result"]
ok(res.get("device_plan") and res.get("audio_url") and not res.get("video_url"), "result has plan + audio url, no video")
plan = res["device_plan"]
ok(plan["out"] == [720, 1280] and len(plan["scenes"]) >= 3 and plan["cues"] and plan["duration"] > 6, f"plan: out {plan['out']}, {len(plan['scenes'])} scenes, {len(plan['cues'])} cues, {plan['duration']:.1f}s")
ok(plan["caption"]["size"] > 10 and plan["fps"] <= 30, "plan: caption size + fps")
a = c.get(res["audio_url"])
ok(a.status_code == 200 and a.headers["content-type"] == "audio/mp4" and len(a.content) > 1000, f"audio file served ({len(a.content)} bytes)")
open(f"{tmp}/a.m4a", "wb").write(a.content)
d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"{tmp}/a.m4a"], capture_output=True, text=True).stdout)
ok(abs(d - plan["duration"]) < 0.3, f"audio length {d:.2f}s matches plan {plan['duration']:.2f}s")
ok(not [f for f in os.listdir(f"{tmp}/out") if f.endswith(".mp4")], "no video file was rendered on the server")
# device log
lg = c.post(f"/api/jobs/{j['id']}/device-log", headers=H, json={"ok": True, "seconds": 5.5, "speed": 8.0, "info": {"cores": 6}})
ok(lg.status_code == 200, "device log accepted")
q = c.get("/api/queue", headers=H).json()
ok("busy" in q and "wait_seconds" in q, "queue status endpoint")
# server fallback = rerender with device_render false
segs = [{"id": s["id"], "start": s["start"], "text": s["text"]} for s in res["project"]["segments"]]
r2 = c.post(f"/api/jobs/{j['id']}/rerender", headers=H, json={"segments": segs, "device_render": False})
j2 = wait(r2.json()["job_id"])
ok(j2["status"] == "done" and j2["result"].get("video_url") and not j2["result"].get("device_plan"), "fallback re-render on the server makes the video")
print("ALL OK")
