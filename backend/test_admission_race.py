"""Offline test: parallel requests cannot get past the per-user limits (security fix: check-then-act race).
Before the fix, N parallel uploads each saw the same 'minutes used' / 'active jobs' and all were admitted.
Run: python test_admission_race.py"""
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  MAX_VIDEO_MINUTES="600", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import capacity  # noqa: E402
import main  # noqa: E402
from db import Job, Session, User  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None      # jobs stay 'queued' = they count as active
main.upload_duration = lambda path: 600.0           # every video is 10 minutes
_decide = capacity.decide


def slow_decide(*a, **k):    # widens the window between "check the limits" and "create the job" so the old race shows up reliably
    time.sleep(0.15)
    return _decide(*a, **k)


capacity.decide = slow_decide


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def make_user(n, daily, monthly=100000):
    with Session() as s:
        u = User(email=f"u{n}@x.com", password_hash=auth.hash_password("password1"), daily_minutes=daily, monthly_minutes=monthly)
        s.add(u)
        s.commit()
        return u.id, auth.make_token(u)


client = TestClient(main.app)


def upload(token):
    return client.post("/api/jobs", headers={"Authorization": f"Bearer {token}"},
                       files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"output": "subtitles"}).status_code


def burst(fn, n=8):
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(lambda _: fn(), range(n)))


def jobs_of(uid):
    with Session() as s:
        return s.query(Job).filter(Job.user_id == uid).all()


# 1. daily allowance of 15 minutes, 10-minute videos, active-job limit out of the way: exactly ONE may be admitted
main.MAX_ACTIVE_JOBS_PER_USER = 50
uid, tok = make_user(1, daily=15)
codes = burst(lambda: upload(tok))
ok(codes.count(200) == 1 and codes.count(402) == 7, f"8 parallel uploads, room for one: {sorted(codes)}")
ok(sum(j.charged_seconds for j in jobs_of(uid)) <= 15 * 60, "charged minutes never exceed the daily allowance")

# 2. monthly allowance
uid, tok = make_user(2, daily=100000, monthly=25)
codes = burst(lambda: upload(tok))
ok(codes.count(200) == 2 and codes.count(402) == 6, f"monthly allowance of 25 min = two 10-min videos: {sorted(codes)}")

# 3. at most MAX_ACTIVE_JOBS_PER_USER jobs queued/running at once
main.MAX_ACTIVE_JOBS_PER_USER = 2
uid, tok = make_user(3, daily=100000)
codes = burst(lambda: upload(tok))
ok(codes.count(200) == 2 and codes.count(429) == 6, f"active-job limit 2: {sorted(codes)}")
ok(len(jobs_of(uid)) == 2, "only two jobs exist in the database")

# 4. the same limit holds for parallel re-renders of a finished video
uid, tok = make_user(4, daily=100000)
src = os.path.join(tmp, "src.mp4")
open(src, "wb").write(b"x")
project = {"voice": "Kore", "source_duration": 100.0, "fx": {}, "segments": [{"id": 1, "start": 1.0, "text": "hello"}]}
with Session() as s:
    s.add(Job(id="done0000001", user_id=uid, status="done", params={"output": "subtitles"}, input_key=src,
              data={"result": {"project": project}}, charged_seconds=60))
    s.commit()


def rerender():
    return client.post("/api/jobs/done0000001/rerender", headers={"Authorization": f"Bearer {tok}"},
                       json={"segments": [{"id": 1, "start": 1.0, "text": "changed"}]}).status_code


codes = burst(rerender)
ok(codes.count(200) == 2 and codes.count(429) == 6, f"parallel re-renders respect the active-job limit: {sorted(codes)}")

# 5. a different user is not blocked by someone else's full allowance
uid5, tok5 = make_user(5, daily=100000)
ok(upload(tok5) == 200, "another user can still upload")

print("ALL OK")
