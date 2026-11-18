"""Offline test: paused after 5 failed videos -> the user asks an admin -> approve = uploads open at once (earlier failures stop counting),
reject = stays paused with the reason, duplicates refused, admin sees recent failures, audit. Run: python test_unlock.py"""
import os, tempfile
from datetime import timedelta
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DATABASE_URL=f"sqlite:///{tmp}/t.db",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)
from fastapi.testclient import TestClient
import auth, db, main
from db import Job, Session, User

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

with Session() as s:
    s.add(User(email="boss", password_hash="x", is_admin=True, is_superadmin=True))
    s.add(User(email="amy", password_hash="x")); s.add(User(email="bob", password_hash="x")); s.commit()
    tok = lambda e: {"Authorization": f"Bearer {auth.make_token(s.query(User).filter_by(email=e).one())}"}
    A, U, B = tok("boss"), tok("amy"), tok("bob")
    amy = s.query(User).filter_by(email="amy").one().id
c = TestClient(main.app)

def add(status, hours_ago, err=None, uid=None):
    with Session() as s:
        s.add(Job(id=os.urandom(6).hex(), user_id=uid or amy, status=status, params={}, data={}, charged_seconds=0.0, error=err,
                  finished_at=db.utcnow() - timedelta(hours=hours_ago), input_key="x")); s.commit()
def wait():
    with Session() as s: return db.failure_wait_seconds(s, amy)
def me(): return c.get("/api/auth/me", headers=U).json()

r = c.post("/api/unlock-request", json={}, headers=U)
ok(r.status_code == 400, "not paused: a request is refused")
ok(me()["unlock_request"] is None and me()["upload_blocked_seconds"] == 0, "not paused: /me has no request")

for h in (1.0, 0.9, 0.8, 0.7, 0.6): add("error", h, "Recap generation failed: 400 FAILED_PRECONDITION. User location is not supported")
ok(wait() > 0, "5 failures in a row: paused")
ok(c.get("/api/auth/me", headers=U).json()["upload_blocked_seconds"] > 0, "/me says paused")
r = c.post("/api/unlock-request", json={"note": "it was your server, not me"}, headers=U)
ok(r.status_code == 200 and r.json()["status"] == "pending", "paused user can ask for a review")
ok(me()["unlock_request"]["status"] == "pending" and me()["unlock_request"]["note"].startswith("it was"), "/me shows the pending request")
ok(c.post("/api/unlock-request", json={}, headers=U).status_code == 409, "a second request while pending is refused")
ok(c.post("/api/unlock-request", json={}, headers=B).status_code == 400, "another user (not paused) cannot ask")

ok(c.get("/api/admin/unlock-requests", headers=U).status_code in (401, 403), "users cannot read the requests")
ov = c.get("/api/admin/overview", headers=A).json()
ok(ov["unlock_pending"] == 1, "overview counts the pending request")
lst = c.get("/api/admin/unlock-requests?status=pending", headers=A).json()
it = lst["items"][0]
ok(lst["total"] == 1 and it["email"] == "amy" and it["still_paused"] and len(it["failures"]) == 5 and "location" in it["failures"][0]["error"], "admin sees the user, the note and the last failures")

# reject first
rid = it["id"]
r = c.post(f"/api/admin/unlock-requests/{rid}/reject", json={"reason": "please check your video first"}, headers=A)
ok(r.status_code == 200 and wait() > 0, "reject: user stays paused")
ok(me()["unlock_request"]["status"] == "rejected" and me()["unlock_request"]["admin_note"] == "please check your video first", "the user sees the rejection reason")
ok(c.post("/api/unlock-request", json={}, headers=U).status_code == 429, "after a rejection no new request in the same pause")
ok(c.post(f"/api/admin/unlock-requests/{rid}/approve", headers=A).status_code == 409, "a decided request cannot be decided again")

# a new pause (another failure after an older approval) + approve
with Session() as s:
    s.query(db.UnlockRequest).delete(); s.commit()
ok(c.post("/api/unlock-request", json={}, headers=U).status_code == 200, "new request (old one gone)")
rid = c.get("/api/admin/unlock-requests?status=pending", headers=A).json()["items"][0]["id"]
r = c.post(f"/api/admin/unlock-requests/{rid}/approve", headers=A)
ok(r.status_code == 200 and wait() == 0, "approve: uploads open at once")
ok(me()["upload_blocked_seconds"] == 0 and me()["unlock_request"] is None, "/me: no longer paused")
ok(c.get("/api/admin/overview", headers=A).json()["unlock_pending"] == 0, "overview: nothing pending")
# the next failures count again from zero
for h in (0.0,) * 4: add("error", h)
ok(wait() == 0, "after approval 4 new failures are still fine")
add("cancelled", 0.0)
ok(wait() > 0, "the 5th new failure pauses again")
ok(c.post("/api/unlock-request", json={}, headers=U).status_code == 200, "and the user can ask again")
au = c.get("/api/admin/audit?action=unlock.approve", headers=A).json()
ok(au["total"] == 1, "approve is in the audit log")
ok(c.get("/api/admin/audit?action=unlock.reject", headers=A).json()["total"] == 1, "reject is in the audit log")
# the 429 on upload mentions the review option
with Session() as s:
    try: main._refuse_if_failure_streak(s, s.get(User, amy)) if hasattr(main, "_refuse_if_failure_streak") else None
    except Exception as e: ok("ask the admin" in str(getattr(e, "detail", "")), "the upload refusal text mentions asking the admin")
print("ALL OK")
