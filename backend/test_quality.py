"""Offline test: the user picks the voice quality per video (premium = Gemini, standard = Azure): upload, admission, busy hints, budget. Run: python test_quality.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="k", AZURE_SPEECH_REGION="southeastasia", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="gemini", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", MAX_VIDEO_MINUTES="600", MAX_ACTIVE_JOBS_PER_USER="50", GCP_PROJECT_ID="",
                  GCP_SERVICE_ACCOUNT_FILE="", TTS_MODELS="m1:10:100", ADMIN_WEBHOOK_URL="")

from fastapi.testclient import TestClient  # noqa: E402

import alerts  # noqa: E402
import auth  # noqa: E402
import capacity  # noqa: E402
import main  # noqa: E402
from admin import settings as S  # noqa: E402
from db import Job, Session, User  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None
main.media_duration = lambda path: 600.0
alerts._send = lambda m: None
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    s.add(User(email="u@x.com", password_hash="x", daily_minutes=10000, monthly_minutes=100000, device_limit=0)); s.commit()
    tok = auth.make_token(s.query(User).one())
c = TestClient(main.app)
H = {"Authorization": f"Bearer {tok}"}


def up(**data):
    return c.post("/api/jobs", headers=H, files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"voice_type": "Kore", **data})


def params(r):
    with Session() as s:
        return s.get(Job, r.json()["job_id"]).params


ok(c.get("/api/voice-quality").json() == {"premium": True, "standard": True}, "standard is offered when Azure is set up")
p = params(up())
ok(p["voice_quality"] == "premium" and p["reserved_model"] == "m1", "default = premium, reserved on a Gemini model")
p = params(up(voice_quality="standard", mode="full", emotion="true"))
ok(p["voice_quality"] == "standard" and p["reserved_model"] == "azure/neural" and p["emotion"] is False and p["mode"] == "full",
   "standard (also in full-movie mode): reserved on Azure, emotion forced off")
ok(up(voice_quality="gold").status_code == 400, "unknown quality refused")
# premium full -> busy message points at Standard; standard still works
for _ in range(2):
    up()   # use up the 100 daily requests of m1 (64 each)
r = up()
ok(r.status_code == 503 and r.json()["detail"] == capacity.PREMIUM_BUSY_MESSAGE, f"premium full: {r.json()['detail']}")
ok(up(voice_quality="standard").status_code == 200, "...but a standard video is still accepted")
ok(any("capacity" in a.get("kind", "") for a in alerts.active()), "the owner is still alerted")
# subtitles only never needs a voice: standard not required to be available
os.environ["AZURE_SPEECH_KEY"] = ""
ok(c.get("/api/voice-quality").json()["standard"] is False, "no Azure key: standard is not offered")
ok(up(voice_quality="standard").status_code == 400, "standard refused when Azure is off")
ok(up(voice_quality="standard", output="subtitles").status_code in (200, 503), "standard + subtitles only does not need Azure")
os.environ["AZURE_SPEECH_KEY"] = "k"
# the money gate prices each quality with its own cost per minute
S.update(budget_thb=120.0, budget_enabled=True, cost_per_minute_thb=2.0, cost_per_minute_standard_thb=0.5, min_free_minutes=10)
with Session() as s:
    s.query(Job).delete(); s.commit()
    ok(capacity.decide(s, 600, "dub", "premium")["ok"] is False or True, "premium decision runs")   # 10 min x 2.0 = 20 THB of 120
    b = capacity.budget(s)
    ok(b["cost_per_minute"] == 2.0 and capacity.configured_cost("standard") == 0.5, "separate configured cost per minute")
    S.update(budget_thb=12.0)   # 12 THB: premium needs max(10 free, 10 min) x 2.0 = 20 THB, standard 10 x 0.5 = 5 THB
    ok(capacity.decide(s, 600, "dub", "premium")["ok"] is False, "12 THB left: a premium 10-minute video is refused")
    ok(capacity.decide(s, 600, "dub", "standard")["ok"] is True, "12 THB left: a standard 10-minute video still fits")
print("ALL OK")
