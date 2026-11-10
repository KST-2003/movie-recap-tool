"""Offline test: self-service sign-ups get a small trial allowance and a global daily cap (security fix: open signup + free quota).
Before: every sign-up got 100 min/day and 2000 min/month, and any number of accounts could be created per day.
Run: python test_signup_policy.py"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
for k in ("SIGNUP_DAILY_MINUTES", "SIGNUP_MONTHLY_MINUTES", "SIGNUP_MAX_PER_DAY", "REDIS_URL"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402

import alerts  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import main  # noqa: E402
import ratelimit  # noqa: E402
from db import Session, User, utcnow  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


client = TestClient(main.app)
ratelimit.REGISTER_PER_IP = (10000, 3600)   # this test is about the daily cap, not the per-address limit
main.SIGNUP_MAX_PER_DAY = 1000


def register(email):
    return client.post("/api/auth/register", json={"email": email, "password": "password123"})


def users_today():
    with Session() as s:
        return s.query(User).count()


# ---- 1. trial allowance ----
ok((config.SIGNUP_DAILY_MINUTES, config.SIGNUP_MONTHLY_MINUTES, config.SIGNUP_MAX_PER_DAY) == (10, 30, 100), "defaults: 10 min/day, 30 min/month, 100 sign-ups/day")
r = register("new1@x.com")
body = r.json()
ok(r.status_code == 200 and body["daily_minutes"] == 10 and body["monthly_minutes"] == 30, f"a self-registered account gets the trial: {body['daily_minutes']} min/day, {body['monthly_minutes']} min/month")
me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + body["token"]}).json()
ok(me["daily_minutes"] == 10 and me["remaining_seconds"] == 10 * 60, "... and the app sees 10 minutes left today")

# an admin-made account keeps the normal allowance, and an admin can raise a trial account
with Session() as s:
    s.add(User(email="root@x.com", password_hash=auth.hash_password("pw-pw-pw-pw"), is_admin=True, daily_minutes=100, monthly_minutes=2000))
    s.commit()
root = client.post("/api/auth/login", json={"email": "root@x.com", "password": "pw-pw-pw-pw"}).json()["token"]
adm = {"Authorization": f"Bearer {root}"}
made = client.post("/api/admin/users", headers=adm, json={"email": "paid@x.com", "password": "password123"}).json()
ok(made["daily_minutes"] == 100 and made["monthly_minutes"] == 2000, "an admin-created account gets the full 100 / 2000")
uid = client.get("/api/admin/users?q=new1", headers=adm).json()["items"][0]["id"]
r = client.patch(f"/api/admin/users/{uid}", headers=adm, json={"daily_minutes": 100, "monthly_minutes": 2000})
ok(r.status_code == 200 and r.json()["daily_minutes"] == 100, "an admin raises a trial account from the dashboard")

# ---- 2. other sign-up rules unchanged ----
ok(register("new1@x.com").status_code == 409, "duplicate e-mail: still refused")
ok(client.post("/api/auth/register", json={"email": "bad", "password": "password123"}).status_code == 400, "bad e-mail: still refused")
main.ALLOW_SIGNUP = False
ok(register("closed@x.com").status_code == 403, "ALLOW_SIGNUP off: still closed")
main.ALLOW_SIGNUP = True

# ---- 3. the daily cap ----
base = users_today()
main.SIGNUP_MAX_PER_DAY = base + 3
codes = [register(f"cap{i}@x.com").status_code for i in range(5)]
ok(codes == [200, 200, 200, 503, 503], f"cap reached after 3 more accounts: {codes}")
r = register("cap9@x.com")
ok(r.json()["detail"] == "Sign-ups are very busy today. Please try again tomorrow.", f"the answer is plain: {r.json()['detail']}")
ok(users_today() == base + 3, "no account was created past the cap")
active = {a["kind"]: a for a in alerts.active()}
ok("signups" in active and active["signups"]["count"] >= 2 and "mass-registering" in active["signups"]["message"], f"the admin got an alert: {active['signups']['message'][:70]}...")
overview = client.get("/api/admin/overview", headers=adm).json()
ok(any(a["kind"] == "signups" for a in overview["alerts"]), "... and it shows on the admin Overview")

# ---- 4. a burst cannot get past the cap ----
with Session() as s:
    s.query(User).filter(User.email.like("cap%")).delete(synchronize_session=False)
    s.commit()
base = users_today()
main.SIGNUP_MAX_PER_DAY = base + 5
with ThreadPoolExecutor(max_workers=12) as ex:
    codes = list(ex.map(lambda i: register(f"burst{i}@x.com").status_code, range(25)))
ok(codes.count(200) == 5 and codes.count(503) == 20, f"25 parallel sign-ups, room for 5: {codes.count(200)} created, {codes.count(503)} refused")
ok(users_today() == base + 5, "exactly 5 accounts exist")

# ---- 5. the cap is per day ----
with Session() as s:
    for u in s.query(User).all():
        u.created_at = utcnow() - timedelta(days=1, hours=1)
    s.commit()
ok(register("tomorrow@x.com").status_code == 200, "next day: sign-ups work again")

# ---- 6. 0 = no cap ----
main.SIGNUP_MAX_PER_DAY = 0
ok(all(register(f"free{i}@x.com").status_code == 200 for i in range(8)), "SIGNUP_MAX_PER_DAY=0 turns the cap off")

# ---- 7. a trial account really is limited ----
main.upload_duration = lambda path: 15 * 60.0
main.jobs_queue.enqueue = lambda job_id: None
trial = client.post("/api/auth/register", json={"email": "trial@x.com", "password": "password123"}).json()["token"]
r = client.post("/api/jobs", headers={"Authorization": f"Bearer {trial}"}, files={"video_file": ("a.mp4", b"x" * 50, "video/mp4")}, data={"output": "subtitles"})
ok(r.status_code == 402 and "Daily limit reached" in r.json()["detail"], f"a trial account cannot upload a 15-minute video ({r.status_code}: {r.json()['detail'][:60]})")

print("ALL OK")
