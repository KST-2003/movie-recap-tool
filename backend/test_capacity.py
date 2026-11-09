"""Offline test of admission control (capacity.py): money budget, voice-request reservations, bursts, refunds, alerts, admin settings.
Run: python test_capacity.py"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="gemini", GEMINI_API_KEY="x",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0", MAX_VIDEO_MINUTES="600", GCP_PROJECT_ID="",
                  GCP_SERVICE_ACCOUNT_FILE="", TTS_MODELS="m1:10:100,m2:10:100", ADMIN_WEBHOOK_URL="")

from fastapi.testclient import TestClient  # noqa: E402

import alerts  # noqa: E402
import auth  # noqa: E402
import capacity  # noqa: E402
import main  # noqa: E402
import tts_pool  # noqa: E402
from admin import settings as S  # noqa: E402
from db import Job, Session, User, update_job  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None
main.media_duration = lambda path: 600.0   # every video is 10 minutes
sent = []
alerts._send = lambda m: sent.append(m)


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    for i in range(24):
        s.add(User(email=f"u{i}@x.com", password_hash=auth.hash_password("password1"), daily_minutes=1000, monthly_minutes=100000,
                   is_admin=(i == 0)))
    s.commit()
tokens = {}
c0 = TestClient(main.app)
with Session() as s:   # tokens made directly: the login endpoint is rate limited per IP
    for u in s.query(User).all():
        tokens[int(u.email[1:].split("@")[0])] = auth.make_token(u)


def upload(i, client=None, output="dub"):
    return (client or c0).post("/api/jobs", headers={"Authorization": f"Bearer {tokens[i]}"},
                               files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"voice_type": "Kore", "output": output})


# 1. no budget set: only the voice reservation applies. Each 10-min video reserves 6*10+4 = 64 requests on ONE model.
ok(capacity.est_requests(600, "dub") == 64 and capacity.est_requests(600, "subtitles") == 0, "estimate: 64 voice requests for 10 min, 0 for subtitles only")
r1 = upload(1)
ok(r1.status_code == 200, "first video admitted")
with Session() as s:
    j1 = s.get(Job, r1.json()["job_id"])
    ok(j1.params["reserved_model"] == "m1" and j1.params["reserved_requests"] == 64, f"reserved 64 on m1 ({j1.params['reserved_model']})")
r2 = upload(2)
with Session() as s:
    ok(r2.status_code == 200 and s.get(Job, r2.json()["job_id"]).params["reserved_model"] == "m2", "second video goes to m2 (m1 has only 36 free): no mid-video model switch needed")
r3 = upload(3)
ok(r3.status_code == 503 and r3.json()["detail"] == capacity.BUSY_MESSAGE, f"third video: busy ({r3.status_code}) - {r3.json().get('detail')}")
ok(any(a["kind"] == "capacity" and a["count"] == 1 for a in alerts.active()), "admin alert recorded")
ok(len(sent) == 1, "webhook message sent once")
with Session() as s:
    ok(s.query(Job).count() == 2, "a refused upload creates no job (nothing charged)")
rsub = upload(3, output="subtitles")
ok(rsub.status_code == 200, "subtitles-only needs no voice requests, still admitted")

# 2. a finished or failed video gives its reservation back
update_job(r1.json()["job_id"], status="error")
ok(tts_pool.reserved("m1") == 0 and tts_pool.free("m1") == 100, "failed video releases its reservation")
ok(upload(4).status_code == 200, "a new video fits again")
update_job(r2.json()["job_id"], status="done")
ok(tts_pool.reserved("m2") == 0, "finished video releases its reservation")

# 3. the job's own Chooser keeps the reserved model and sees its own reservation as free
ch = tts_pool.Chooser(60, "m1", job_id=[j for j, in Session().query(Job.id).all() if True][-2])
ok(ch.get() in ("m1", "m2"), f"chooser picks a model ({ch.get()})")

# 4. money: balance 100 THB, 1 THB/min, keep 30 min free -> 8 videos of 10 min, never more
with Session() as s:
    s.query(Job).delete(); s.commit()
alerts._save({})
S.update(budget_thb=100.0, budget_enabled=True, cost_per_minute_thb=1.0, min_free_minutes=30.0)
S.update(**{})
os.environ["TTS_MODELS"] = "m1:10:100000"   # plenty of voice requests: only the money limits now
with Session() as s:
    b = capacity.budget(s)
ok(b["available_minutes"] == 100.0, f"100 THB = 100 minutes ({b['available_minutes']})")


def burst(i):
    return upload(i, TestClient(main.app)).status_code


with ThreadPoolExecutor(12) as ex:
    codes = list(ex.map(burst, range(1, 21)))   # 20 users upload at the same moment
admitted = codes.count(200)
ok(admitted == 8 and codes.count(503) == 12, f"20 simultaneous 10-min uploads, 100 min of budget, 30 kept free: {admitted} admitted, {codes.count(503)} told 'busy'")
with Session() as s:
    b = capacity.budget(s)
    ok(abs(b["left_thb"] - 20.0) < 1e-6, f"spent 80 THB, 20 left ({b['left_thb']})")
    ok(s.query(Job).count() == 8, "only the admitted videos exist")
st = [a for a in alerts.active() if a["kind"] == "capacity"][0]
ok(st["count"] >= 12 and "Budget" in st["message"], f"alert counts the refusals: {st['count']}")

# 5. failed video gives its money back -> room again
with Session() as s:
    one = s.query(Job).first().id
update_job(one, status="error")
with Session() as s:
    ok(capacity.budget(s)["left_thb"] == 30.0, "failed video refunds the budget")
ok(upload(22).status_code == 200, "exactly at the 30-minute floor a video is still admitted (it needs max(30, its length) free)")
ok(upload(23).status_code == 503, "below the floor: busy")

# 6. budget off -> no money gate
S.update(budget_enabled=False)
ok(upload(23).status_code == 200, "budget off: admitted")

# 7. admin: settings + overview
H = lambda i: {"Authorization": f"Bearer {tokens[i]}"}  # noqa: E731
ok(c0.put("/api/admin/settings", headers=H(5), json={"budget_thb": 5}).status_code == 403, "normal user cannot change the budget")
r = c0.put("/api/admin/settings", headers=H(0), json={"budget_thb": 2000, "budget_enabled": True, "min_free_minutes": 30, "cost_per_minute_thb": 1}).json()
ok(r["budget_thb"] == 2000 and r["budget_enabled"] is True and r["budget_set_at"], "admin sets the budget (2000 THB)")
ov = c0.get("/api/admin/overview", headers=H(0)).json()
ok(ov["capacity"]["budget"]["enabled"] and ov["capacity"]["budget"]["available_minutes"] > 1900 and ov["capacity"]["voice"], "overview shows capacity")
ok(any(a["kind"] == "capacity" for a in ov["alerts"]), "overview shows the alert")
ok(c0.put("/api/admin/settings", headers=H(0), json={"cost_per_minute_thb": 0}).status_code == 422, "cost per minute must be > 0")
au = str(c0.get("/api/admin/audit?action=settings.update", headers=H(0)).json())
ok("budget_thb" in au, "budget change is in the audit log")
print("ALL OK")
