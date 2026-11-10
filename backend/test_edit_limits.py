"""Offline test: editor previews and re-renders are limited per video and per day, counted in the database.
Defaults: 10 previews / 5 re-renders per video, 30 previews / 15 re-renders per user per day.
Before this fix both were free and unlimited (the old preview counter was in process memory).
Run: python test_edit_limits.py"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
# the numbers below are the ones this test was written with; the real defaults are checked at the end
os.environ.update(PREVIEWS_PER_VIDEO="10", PREVIEWS_PER_DAY="30", RERENDERS_PER_VIDEO="5", RERENDERS_PER_DAY="15")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import edit_limits  # noqa: E402
import main  # noqa: E402
from api import jobs as api_jobs  # noqa: E402
import pipeline  # noqa: E402
from db import EditUse, Job, Session, User, utcnow  # noqa: E402

api_jobs.jobs_queue.enqueue = lambda job_id: None
api_jobs.MAX_ACTIVE_JOBS_PER_USER = 1000   # these tests are about the edit limits, not the active-job limit
client = TestClient(main.app)
src = os.path.join(tmp, "src.mp4")
open(src, "wb").write(b"x")


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def make_user(n):
    with Session() as s:
        u = User(email=f"u{n}@x.com", password_hash=auth.hash_password("password1"), daily_minutes=1000, monthly_minutes=100000)
        s.add(u)
        s.commit()
        return u.id, {"Authorization": "Bearer " + auth.make_token(u)}


def make_video(uid, jid):
    project = {"voice": "Kore", "source_duration": 100.0, "fx": {}, "segments": [{"id": 1, "start": 1.0, "text": "hello"}]}
    with Session() as s:
        s.add(Job(id=jid, user_id=uid, status="done", params={"output": "subtitles"}, input_key=src,
                  data={"result": {"project": project}}, charged_seconds=60))
        s.commit()


def preview(h, jid, text):
    return client.post(f"/api/jobs/{jid}/preview-line", headers=h, json={"id": 1, "text": text, "voice": "Kore"})


def rerender(h, jid, text="changed"):
    return client.post(f"/api/jobs/{jid}/rerender", headers=h, json={"segments": [{"id": 1, "start": 1.0, "text": text}]})


def uses(uid, kind, vid=None):
    with Session() as s:
        q = s.query(EditUse).filter(EditUse.user_id == uid, EditUse.kind == kind)
        return (q.filter(EditUse.video_id == vid) if vid else q).count()


# ---- previews: 10 per video ----
a, ha = make_user(1)
make_video(a, "video0000001")
codes = [preview(ha, "video0000001", f"line number {i}").status_code for i in range(10)]
ok(codes == [200] * 10, "10 previews of one video are allowed")
r = preview(ha, "video0000001", "one too many")
ok(r.status_code == 429 and "all 10 voice previews" in r.json()["detail"], f"the 11th is refused: {r.status_code} {r.json().get('detail')}")
ok(uses(a, "preview") == 10, "the refused one was not counted")
r = preview(ha, "video0000001", "line number 3")
ok(r.status_code == 200, "repeating a line that is already voiced comes from the cache: free, allowed at the limit")
ok(uses(a, "preview") == 10, "a cached preview is not counted")

# ---- previews: 30 per user per day across videos ----
make_video(a, "video0000002")
make_video(a, "video0000003")
make_video(a, "video0000004")
for vid in ("video0000002", "video0000003"):
    codes = [preview(ha, vid, f"{vid} line {i}").status_code for i in range(10)]
    ok(codes == [200] * 10, f"10 previews of {vid} allowed (daily total so far {uses(a, 'preview')})")
r = preview(ha, "video0000004", "a fourth video")
ok(r.status_code == 429 and "Daily limit" in r.json()["detail"], f"31st preview of the day is refused: {r.json().get('detail')}")

# ---- another user is not affected ----
b, hb = make_user(2)
make_video(b, "video0000005")
ok(preview(hb, "video0000005", "hello there").status_code == 200, "another user can still preview")
ok(preview(hb, "video0000001", "not mine").status_code == 404, "and cannot preview someone else's video")

# ---- a failed voice request gives the use back ----
c, hc = make_user(3)
make_video(c, "video0000006")
real = pipeline.voice_many


def boom(*args, **kwargs):
    raise RuntimeError("voice service down")


pipeline.voice_many = boom
r = preview(hc, "video0000006", "this will fail")
pipeline.voice_many = real
ok(r.status_code == 502 and uses(c, "preview") == 0, f"failed preview: 502 and not counted ({uses(c, 'preview')} used)")

# ---- parallel clicks cannot get past the limit ----
d, hd = make_user(4)
make_video(d, "video0000007")
with ThreadPoolExecutor(max_workers=10) as ex:
    codes = list(ex.map(lambda i: preview(hd, "video0000007", f"parallel {i}").status_code, range(20)))
ok(codes.count(200) == 10 and codes.count(429) == 10, f"20 parallel previews, limit 10: {codes.count(200)} ok, {codes.count(429)} refused")
ok(uses(d, "preview", "video0000007") == 10, "exactly 10 recorded")

# ---- re-renders: 5 per video ----
e, he = make_user(5)
make_video(e, "video0000008")
codes = [rerender(he, "video0000008", f"v{i}").status_code for i in range(5)]
ok(codes == [200] * 5, "5 re-renders of one video are allowed")
r = rerender(he, "video0000008", "v6")
ok(r.status_code == 429 and "all 5 re-renders" in r.json()["detail"], f"the 6th is refused: {r.json().get('detail')}")
ok(uses(e, "rerender") == 5, "the refused one was not counted and created no job")
with Session() as s:
    jobs = s.query(Job).filter(Job.user_id == e, Job.id != "video0000008").all()
    ok(len(jobs) == 5, f"5 new jobs exist ({len(jobs)})")
    new = jobs[0]
    ok(edit_limits.video_id(new) == "video0000008", "a re-render counts against the ORIGINAL video (bg_source_job)")

# ---- re-renders: 15 per user per day ----
for n in (9, 10):
    make_video(e, f"video00000{n:02d}")
for vid in ("video0000009", "video0000010"):
    codes = [rerender(he, vid, f"{vid}{i}").status_code for i in range(5)]
    ok(codes == [200] * 5, f"5 re-renders of {vid}")
make_video(e, "video0000011")
r = rerender(he, "video0000011")
ok(r.status_code == 429 and "Daily limit" in r.json()["detail"], f"16th re-render of the day is refused: {r.json().get('detail')}")

# ---- the daily counter resets with the day (the per-video one does not) ----
with Session() as s:
    for use in s.query(EditUse).all():
        use.created_at = utcnow() - timedelta(days=1, hours=1)
    s.commit()
ok(rerender(he, "video0000011").status_code == 200, "next day: a new video can be re-rendered again")
ok(rerender(he, "video0000008", "again").status_code == 429, "but the per-video limit of an old video stays")
ok(preview(ha, "video0000004", "fresh day").status_code == 200, "next day: previews work again")

# ---- the defaults a fresh install gets (doubled on request) ----
import subprocess  # noqa: E402
import sys  # noqa: E402

clean = {k: v for k, v in os.environ.items() if k not in ("PREVIEWS_PER_VIDEO", "PREVIEWS_PER_DAY", "RERENDERS_PER_VIDEO", "RERENDERS_PER_DAY")}
out = subprocess.run([sys.executable, "-c", "import edit_limits;print(edit_limits.LIMITS['preview'][:2], edit_limits.LIMITS['rerender'][:2])"],
                     capture_output=True, text=True, env=clean).stdout.strip().splitlines()[-1]
ok(out == "(20, 60) (10, 30)", f"defaults: previews 20 per video / 60 per day, re-renders 10 per video / 30 per day ({out})")

print("ALL OK")
