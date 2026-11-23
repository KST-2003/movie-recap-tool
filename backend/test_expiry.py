"""Offline test: accounts made for N months: end date set at creation, login refused and sessions stopped once it has passed,
extending / removing the end date, admins never expire, audit. Run: python test_expiry.py"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
from db import AuditLog, Session, User, add_months, utcnow  # noqa: E402



def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


U = timezone.utc
ok(add_months(datetime(2026, 1, 31, 10, tzinfo=U), 1) == datetime(2026, 2, 28, 10, tzinfo=U), "31 Jan + 1 month = 28 Feb")
ok(add_months(datetime(2026, 11, 15, tzinfo=U), 3) == datetime(2027, 2, 15, tzinfo=U) and add_months(datetime(2026, 11, 15, tzinfo=U), 12).year == 2027, "months roll over the year")

with Session() as s:
    s.add_all([User(email="boss", password_hash="x", is_admin=True, is_superadmin=True), User(email="old", password_hash=auth.hash_password("password123"))])
    s.commit()
    B = {"Authorization": f"Bearer {auth.make_token(s.query(User).filter_by(email='boss').one())}"}
c = TestClient(main.app)
login = lambda name, pw: c.post("/api/auth/login", json={"email": name, "password": pw, "device_id": "device-0001"})
days_left = lambda iso: (datetime.fromisoformat(iso) - utcnow()).total_seconds() / 86400

r = c.post("/api/admin/users", headers=B, json={"username": "amy", "months": 3}).json()
ok(r["expires_at"] and 88 <= days_left(r["expires_at"]) <= 93 and r["expired"] is False, f"3 months chosen -> end date about 3 months away ({days_left(r['expires_at']):.0f} days)")
amy, pw = r["id"], r["password"]
r0 = c.post("/api/admin/users", headers=B, json={"username": "free"}).json()
ok(r0["expires_at"] is None, "no months chosen -> no end date")
ra = c.post("/api/admin/users", headers=B, json={"username": "helper", "role": "admin", "months": 1}).json()
ok(ra["expires_at"] is None, "an admin account never gets an end date")
ok(c.post("/api/admin/users", headers=B, json={"username": "bad", "months": -1}).status_code == 422, "months cannot be negative")

t = login("amy", pw)
ok(t.status_code == 200 and t.json()["expires_at"], "inside the months: login works and the app is told the end date")
H = {"Authorization": f"Bearer {t.json()['token']}"}
ok(c.get("/api/auth/me", headers=H).status_code == 200, "and the session works")
ok(login("old", "password123").json()["expires_at"] is None, "accounts made before this (no end date) keep working")


def set_end(uid, when):
    with Session() as s:
        s.get(User, uid).expires_at = when
        s.commit()


set_end(amy, utcnow() - timedelta(minutes=1))
r = c.get("/api/auth/me", headers=H)
ok(r.status_code == 401 and "its time has ended" in r.json()["detail"], "after the end date an open session is stopped with a clear text")
r = login("amy", pw)
ok(r.status_code == 403 and "its time has ended" in r.json()["detail"], "and a new login is refused with the same text")
ok(login("amy", "wrong-password").status_code == 401 and "Wrong" in login("amy", "wrong-password").json()["detail"], "a wrong password still only says wrong password")
row = [u for u in c.get("/api/admin/users?q=amy", headers=B).json()["items"] if u["email"] == "amy"][0]
ok(row["expired"] is True, "the admin list marks the account as expired")

r = c.patch(f"/api/admin/users/{amy}", headers=B, json={"extend_months": 1}).json()
ok(27 <= days_left(r["expires_at"]) <= 32 and r["expired"] is False, "renewing an EXPIRED account counts from today")
ok(login("amy", pw).status_code == 200 and c.get("/api/auth/me", headers=H).status_code == 200, "after renewing the login (and the old session) work again")
r = c.patch(f"/api/admin/users/{amy}", headers=B, json={"extend_months": 6}).json()
ok(208 <= days_left(r["expires_at"]) <= 216, f"renewing a RUNNING account adds to its end date ({days_left(r['expires_at']):.0f} days)")
r = c.patch(f"/api/admin/users/{amy}", headers=B, json={"no_expiry": True}).json()
ok(r["expires_at"] is None, "the end date can be removed")
r = c.patch(f"/api/admin/users/{r0['id']}", headers=B, json={"extend_months": 1}).json()
ok(27 <= days_left(r["expires_at"]) <= 32, "an account without an end date can be given one")

set_end(ra["id"], utcnow() - timedelta(days=1))
ok(login("helper", ra["password"]).status_code == 200, "an admin is never locked out by an end date")
with Session() as s:
    made = s.query(AuditLog).filter_by(action="user.create", target_label="amy").one().details
    ups = [a.details for a in s.query(AuditLog).filter_by(action="user.update", target_label="amy").order_by(AuditLog.id).all()]
ok(made["months"] == 3 and made["expires_at"], "audit: the months given at creation")
ok(len(ups) == 3 and ups[0]["expires_at"]["months"] == 1 and ups[2]["expires_at"]["to"] is None, "audit: each renewal and the removal")

# ---- deleting an account: only a suspended one ----
ok(c.delete(f"/api/admin/users/{amy}", headers=B).status_code == 400 and "Suspend" in c.delete(f"/api/admin/users/{amy}", headers=B).json()["detail"], "an ACTIVE account cannot be deleted: suspend first")
c.patch(f"/api/admin/users/{amy}", headers=B, json={"status": "paused"})
r = login("amy", pw)
ok(r.status_code == 403 and "suspended" in r.json()["detail"], "a suspended (paused) account is told so")
from db import Job, TopupRequest, UserDevice  # noqa: E402
os.makedirs(f"{tmp}/data/slips", exist_ok=True)
open(f"{tmp}/data/slips/slip_amy.png", "wb").write(b"x")
open(f"{tmp}/up/amy_src.mp4", "wb").write(b"x")
open(f"{tmp}/out/amy_out.mp4", "wb").write(b"x")
with Session() as s:
    s.add(Job(id="amyjob", user_id=amy, status="running", input_key=f"{tmp}/up/amy_src.mp4", params={}, data={"result": {"video_file": "amy_out.mp4"}}))
    s.add(TopupRequest(user_id=amy, minutes=30, price_per_minute=5, amount_thb=150, slip_file="slip_amy.png"))
    s.commit()
ok(c.delete(f"/api/admin/users/{amy}", headers=B).status_code == 409, "not while one of the user's videos is still in progress")
db.update_job("amyjob", status="done")
HA = {"Authorization": f"Bearer {auth.make_token_for_test(ra['id']) if hasattr(auth, 'make_token_for_test') else login('helper', ra['password']).json()['token']}"}
ok(c.delete(f"/api/admin/users/{amy}", headers=HA).status_code == 200, "an admin can delete a suspended user")
with Session() as s:
    left = (s.get(User, amy), s.query(Job).filter_by(user_id=amy).count(), s.query(TopupRequest).filter_by(user_id=amy).count(), s.query(UserDevice).filter_by(user_id=amy).count())
    log = s.query(AuditLog).filter_by(action="user.delete").one()
ok(left == (None, 0, 0, 0), "the account, its videos, top-up requests and devices are gone")
ok(not os.path.exists(f"{tmp}/data/slips/slip_amy.png") and not os.path.exists(f"{tmp}/up/amy_src.mp4") and not os.path.exists(f"{tmp}/out/amy_out.mp4"), "and so are its files (slip, source, result)")
ok(log.target_label == "amy" and log.details["videos"] == 1 and log.details["topups"] == 1, "the audit log keeps who was deleted and what went with it")
ok(login("amy", pw).status_code == 401, "the deleted login no longer exists")
ok(c.post("/api/admin/users", headers=B, json={"username": "amy"}).status_code == 200, "the username is free again")
set_end(r0["id"], utcnow() - timedelta(days=1))
ok(c.delete(f"/api/admin/users/{r0['id']}", headers=B).status_code == 200, "an account whose time has ended counts as suspended: it can be deleted")
c.patch(f"/api/admin/users/{ra['id']}", headers=B, json={"status": "paused"})
with Session() as s:
    s.add(User(email="helper2", password_hash="x", is_admin=True)); s.commit()
    H2 = {"Authorization": f"Bearer {auth.make_token(s.query(User).filter_by(email='helper2').one())}"}
    boss_id = s.query(User).filter_by(email="boss").one().id
ok(c.delete(f"/api/admin/users/{ra['id']}", headers=H2).status_code == 403, "an admin cannot delete another admin")
ok(c.delete(f"/api/admin/users/{boss_id}", headers=H2).status_code == 403 and c.delete(f"/api/admin/users/{boss_id}", headers=B).status_code == 400, "nobody can delete the owner (or themselves)")
ok(c.delete(f"/api/admin/users/{ra['id']}", headers=B).status_code == 200 and c.delete("/api/admin/users/99999", headers=B).status_code == 404, "the owner can delete a suspended admin; unknown user -> 404")
print("all expiry tests passed")
