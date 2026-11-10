"""Offline test: the start-up work still runs after moving from the deprecated @app.on_event to a lifespan handler.
Run: python test_lifespan.py"""
import os
import tempfile
import threading
import warnings

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
os.environ.pop("REDIS_URL", None)

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    from fastapi.testclient import TestClient  # noqa: E402

    import auth  # noqa: E402
    import main  # noqa: E402
    from db import Job, Session, User  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


ok(not [w for w in caught if "on_event" in str(w.message)], "no 'on_event is deprecated' warning any more")
ok(not main.app.router.on_startup, "no old-style start-up handler is registered")

with Session() as s:
    u = User(email="a@x.com", password_hash=auth.hash_password("password123"), daily_minutes=10, monthly_minutes=10)
    s.add(u)
    s.commit()
    for jid, status in (("job_queued_01", "queued"), ("job_running_1", "running"), ("job_done_0001", "done")):
        s.add(Job(id=jid, user_id=u.id, status=status, params={}, data={}, charged_seconds=60.0))
    s.commit()


def job(jid):
    with Session() as s:
        return s.get(Job, jid)


before = {t.name for t in threading.enumerate()}
with TestClient(main.app) as client:   # entering the context runs the lifespan start-up
    ok(client.get("/health").json() == {"ok": True}, "the server answers inside the lifespan")
    q, r, d = job("job_queued_01"), job("job_running_1"), job("job_done_0001")
    ok(q.status == "error" and r.status == "error", "jobs left queued / running by the previous process are marked failed")
    ok(q.stage == "Interrupted" and "restarted" in q.error and q.charged_seconds == 0.0, f"... with a plain message and the minutes refunded ({q.error[:50]}...)")
    ok(d.status == "done" and d.charged_seconds == 60.0, "a finished job is left alone")
    ok(len(threading.enumerate()) >= len(before) + 1, "the clean-up thread for old files was started")

print("ALL OK")
