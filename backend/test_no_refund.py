"""Offline: a video that STARTED and then fails / is cancelled keeps the user's minutes (allowance and bought); one that never left
the waiting line gives them back; REFUND_UNFINISHED=1 restores the old refund. Run: python test_no_refund.py"""
import os, tempfile, importlib
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db", TTS_PROVIDER="fake")
import config, db
from db import Job, Session, User, update_job, used_seconds_today

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

with Session() as s:
    u = User(email="a@example.com", password_hash="x", credit_seconds=0.0); s.add(u); s.commit(); uid = u.id
def make(jid, status):
    with Session() as s:
        s.add(Job(id=jid, user_id=uid, status=status, charged_seconds=300.0, credit_seconds=120.0, params={})); s.commit()
def state(jid):
    with Session() as s:
        j = s.get(Job, jid); return j.charged_seconds, j.credit_seconds, s.get(User, uid).credit_seconds, used_seconds_today(s, uid)

make("run_fail", "running"); update_job("run_fail", status="error", error="boom")
ok(state("run_fail")[:3] == (300.0, 120.0, 0.0), "a started video that fails keeps its allowance and bought minutes")
ok(state("run_fail")[3] == 300.0, "and still counts in today's used minutes")
make("run_cancel", "running"); update_job("run_cancel", status="cancelled")
ok(state("run_cancel")[:3] == (300.0, 120.0, 0.0), "a started video that is cancelled keeps them too")
make("q_cancel", "queued"); update_job("q_cancel", status="cancelled")
ok(state("q_cancel")[:3] == (0.0, 0.0, 120.0), "a video cancelled while still waiting in line gives everything back")
make("ok", "running"); update_job("ok", status="done")
ok(state("ok")[:2] == (300.0, 120.0), "a finished video is charged as before")
config.REFUND_UNFINISHED = True
make("old", "running"); update_job("old", status="error")
ok(state("old")[:3] == (0.0, 0.0, 240.0), "REFUND_UNFINISHED=1: the old refund is back")
print("ALL OK")
