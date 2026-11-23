"""Offline test: /api/queue says premium_busy exactly when an upload with the High-quality voice would be refused.
Run: python test_premium_busy.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="gemini", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  MAX_VIDEO_MINUTES="10", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", TTS_MODELS="m1:10:100,m2:10:100", ADMIN_WEBHOOK_URL="")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import tts_pool  # noqa: E402
from db import Job, Session, User  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None
main.media_duration = lambda path: 600.0
main.real_media_duration = lambda path, **k: 600.0


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    for e in ("u@x.com", "v@x.com"):
        s.add(User(email=e, password_hash=auth.hash_password("password1"), daily_minutes=1000, monthly_minutes=100000))
    s.commit()
    tok, tok2 = (auth.make_token(u) for u in s.query(User).order_by(User.id).all())
c = TestClient(main.app)
H = {"Authorization": f"Bearer {tok}"}


def busy(seconds=None):
    r = c.get("/api/queue", headers=H, params={"seconds": seconds} if seconds else {})
    assert r.status_code == 200, r.text
    return r.json()["premium_busy"]


def upload(h=None):
    return c.post("/api/jobs", headers=h or H, files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"voice_type": "Kore", "output": "dub"})


ok(busy() is False and busy(600) is False, "fresh day: High quality free")
# two 10-min videos reserve 64 each, one per model: 36 left on each, so a third 10-min video would be refused
r1, r2 = upload(), upload()
ok(r1.status_code == 200 and r2.status_code == 200, "two 10-min videos admitted")
ok(busy(600) is True, "a third 10-min video: busy")
r3 = upload({"Authorization": f"Bearer {tok2}"}); ok(r3.status_code == 503, f"...and the upload is refused ({r3.status_code} {r3.text[:80]})")
ok(busy(60) is False and busy() is False, "a 1-min video (needs 10) still fits: not busy")
ok(busy(5 * 60) is False and busy(6 * 60) is True, "5 min (34 requests) fits in 36, 6 min (40) does not")
ok(busy(10 ** 6) is True, "absurd length is capped at the 10-minute limit, still busy")
# videos end: their reservation is released
with Session() as s:
    for j in s.query(Job).all():
        j.status = "done"
    s.commit()
ok(busy(600) is False, "reservations released: free again")
# check failing never blocks the choice
orig = tts_pool.admit
tts_pool.admit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
ok(busy(600) is False, "a failing check does not show Busy")
tts_pool.admit = orig
print("all passed")
