"""Offline test: the limits cannot be beaten by acting at the same moment, and the "free pass" cannot be faked (security audit 2026-11-19,
findings 3 and 4). Real-life scenarios:
  1. Six uploads fired at the same moment by one user, whose limit is 2 videos at a time: exactly 2 get in.
  2. Five uploads at the same moment by a user with 60 s of allowance left (40 s videos): exactly one fits, nobody overspends.
  3. "Ko Aung" tries the hidden `fallback` free pass on a server-rendered video, and on a phone-rendered video with a changed script / no
     device_render flag / changed voice: every try is refused, nothing is created, his 3 free re-renders are untouched. The real fallback
     (unchanged lines, phone-rendered video) still works once and is free.
  4. A re-render that was started and then cancelled or failed still counts toward the 3 free; one that never started does not.
Soft checks: every scenario runs even if an earlier one fails, so it can be run against the OLD code to see what used to be possible.
Run: python test_admission.py"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DUB_PROVIDER="gemini", TTS_BULK="0", DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="",
                  MAX_ACTIVE_JOBS_PER_USER="2", ALLOW_SIGNUP="true")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)
from fastapi.testclient import TestClient  # noqa: E402
import auth  # noqa: E402
import gemini_dub  # noqa: E402
import jobs_queue  # noqa: E402
import main  # noqa: E402
from db import Job, Session, User  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        FAILS.append(msg)


# jobs really run (so they stay "active") only in the upload scenarios; the dub step waits until we let it go
RUN = {"on": False}
RELEASE = threading.Event()
real_enqueue = jobs_queue.enqueue
jobs_queue.enqueue = lambda job_id: real_enqueue(job_id) if RUN["on"] else None


def fake_dub(path, target, **kw):
    RELEASE.wait(timeout=600)
    return "zh", gemini_dub.finish_segments([{"start": 0.0, "end": 3.0, "source_text": "x", "translated_text": "မင်္ဂလာပါ။"}], [])


gemini_dub.dub = fake_dub


def make(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=160x120:r=5:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", path], check=True)


with Session() as s:
    s.add_all([User(email="amy", password_hash="x", daily_minutes=1000, monthly_minutes=100000),
               User(email="bo", password_hash="x", daily_minutes=1, monthly_minutes=100000),     # 60 s of allowance, no bought minutes
               User(email="ko", password_hash="x", daily_minutes=1000, monthly_minutes=100000)])
    s.commit()
    H = {u.email: {"Authorization": f"Bearer {auth.make_token(u)}"} for u in s.query(User).all()}
c = TestClient(main.app)


def upload(who, data):
    return c.post("/api/jobs", headers=H[who], files={"video_file": ("a.mp4", data, "video/mp4")}, data={"voice_type": "su", "fit_translation": "false", "resolution": "720"}).status_code


def jobs_of(email):
    with Session() as s:
        uid = s.query(User).filter_by(email=email).one().id
        return s.query(Job).filter_by(user_id=uid).all()


# ---------------------------------------------------------------- 1. six uploads at the same moment, limit 2 at a time
RUN["on"] = True
make(f"{tmp}/short.mp4", 8)
short = open(f"{tmp}/short.mp4", "rb").read()
with ThreadPoolExecutor(max_workers=6) as pool:
    codes = list(pool.map(lambda _: upload("amy", short), range(6)))
check(codes.count(200) == 2 and codes.count(429) == 4, f"1. six simultaneous uploads, limit 2 at a time: exactly 2 get in, 4 are told to wait {sorted(codes)}")
check(len(jobs_of("amy")) == 2, f"1. only 2 jobs exist ({len(jobs_of('amy'))})")

# ---------------------------------------------------------------- 2. five uploads at the same moment, 60 s of allowance, 40 s each
main.MAX_ACTIVE_JOBS_PER_USER = 10   # so only the allowance can stop them
make(f"{tmp}/forty.mp4", 40)
forty = open(f"{tmp}/forty.mp4", "rb").read()
with ThreadPoolExecutor(max_workers=5) as pool:
    codes = list(pool.map(lambda _: upload("bo", forty), range(5)))
charged = sum((j.charged_seconds or 0) + (j.credit_seconds or 0) for j in jobs_of("bo"))
check(codes.count(200) == 1 and codes.count(402) == 4, f"2. five simultaneous 40 s uploads on 60 s of allowance: exactly one fits {sorted(codes)}")
check(charged <= 60.5, f"2. nobody overspent the allowance (charged {charged:.1f} s of 60)")
main.MAX_ACTIVE_JOBS_PER_USER = 2
RUN["on"] = False

# ---------------------------------------------------------------- 3. Ko Aung and the hidden "my phone failed" pass
src_srv, src_dev = f"{tmp}/up/srv.mp4", f"{tmp}/up/dev.mp4"
open(src_srv, "wb").write(b"x"); open(src_dev, "wb").write(b"x")
project = {"source_duration": 600.0, "voice": "Kore", "fx": {}, "segments": [{"id": 1, "start": 0.0, "end": 5.0, "text": "hello", "source_text": "", "speaker": None}]}
with Session() as s:
    ko = s.query(User).filter_by(email="ko").one()
    s.add(Job(id="koserver0001", user_id=ko.id, status="done", params={"output": "subtitles"}, data={"result": {"project": project}}, input_key=src_srv, charged_seconds=600.0))
    s.add(Job(id="kodevice0001", user_id=ko.id, status="done", params={"output": "subtitles", "device_render": True},
              data={"result": {"project": project, "device_plan": {"duration": 600}}}, input_key=src_dev, charged_seconds=600.0))
    s.commit()
price = lambda jid: c.get(f"/api/jobs/{jid}/edit-price", headers=H["ko"]).json()
rerender = lambda jid, body: c.post(f"/api/jobs/{jid}/rerender", headers=H["ko"], json=body).status_code
before = len(jobs_of("ko"))
new_script = lambda i: [{"id": 1, "start": 0.0, "text": f"a completely new script {i}"}]
codes = [rerender("koserver0001", {"segments": new_script(i), "fallback": True}) for i in range(10)]
check(set(codes) == {400}, f"3. 10 'my phone failed' claims on a video that was not made on a phone, with a new script: all refused {sorted(set(codes))}")
codes = [rerender("kodevice0001", {"segments": new_script(i), "device_render": False, "fallback": True}) for i in range(5)]
check(set(codes) == {400}, f"3. same claim on a phone-made video but with a changed script: all refused {sorted(set(codes))}")
same = [{"id": 1, "start": 0.0, "text": "hello", "source_text": "", "speaker": None, "tempo": None}]
check(rerender("kodevice0001", {"segments": same, "fallback": True}) == 400, "3. claim without saying the server should render: refused")
check(rerender("kodevice0001", {"segments": same, "device_render": False, "fallback": True, "voice_type": "su"}) == 400, "3. claim plus a changed voice: refused")
check(rerender("kodevice0001", {"segments": same, "device_render": False, "fallback": True, "enable_flip": True}) == 400, "3. claim plus a changed setting: refused")
check(len(jobs_of("ko")) == before, f"3. none of those created a job or cost anything ({len(jobs_of('ko')) - before} new jobs)")
check(price("koserver0001")["free_left"] == 3 and price("kodevice0001")["free_left"] == 3, "3. his 3 free re-renders are still all there")
r = c.post("/api/jobs/kodevice0001/rerender", headers=H["ko"], json={"segments": same, "device_render": False, "fallback": True})
with Session() as s:
    made = s.get(Job, r.json()["job_id"]) if r.status_code == 200 else None
    free = made is not None and (made.charged_seconds, made.credit_seconds) == (0, 0)
check(r.status_code == 200 and free, "3. the REAL fallback (phone-made video, nothing changed) still works and is free")
check(price("kodevice0001")["free_left"] == 3, "3. ... and it does not use up one of the 3")
check(rerender("kodevice0001", {"segments": same, "device_render": False, "fallback": True}) == 409, "3. ... but it can be used only once for that video")

# ---------------------------------------------------------------- 4. started-then-stopped re-renders still count
edit = {"edit": {"segments": []}}
def add(job_id, status, data):
    with Session() as s:
        ko = s.query(User).filter_by(email="ko").one()
        s.add(Job(id=job_id, user_id=ko.id, status=status, params=edit, data=data, input_key=src_srv)); s.commit()
check(price("koserver0001")["free_left"] == 3, "4. start: 3 free left")
add("cancelstart01", "cancelled", {"started_at": 1})
check(price("koserver0001")["free_left"] == 2, "4. a re-render started and then CANCELLED still uses one free re-render")
add("cancelnever01", "cancelled", {})
check(price("koserver0001")["free_left"] == 2, "4. one cancelled before it ever started does not")
add("errorstart001", "error", {"started_at": 1})
check(price("koserver0001")["free_left"] == 1, "4. one that started and FAILED uses one")
add("errornever001", "error", {})
check(price("koserver0001")["free_left"] == 1, "4. one that failed before starting does not")
add("donejob00001", "done", {})
q = price("koserver0001")
check(q["free_left"] == 0 and q["cost_minutes"] == 4, f"4. after 3 used the next one costs 4 minutes (40 % of 10): {q['cost_minutes']}")

print(f"\n{'ALL OK' if not FAILS else 'FAILED: ' + str(len(FAILS)) + ' check(s)'}", flush=True)
sys.stdout.flush()
os._exit(1 if FAILS else 0)   # the upload jobs are still waiting in their gate: do not wait for them
