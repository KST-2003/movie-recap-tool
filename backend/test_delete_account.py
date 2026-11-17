"""Offline test: a user deletes their own account (App Store / Google Play rule).
Run: python test_delete_account.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from db import AuditLog, Job, Preset, Review, Session, User, UserDevice  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    s.add_all([User(email="amy", password_hash=auth.hash_password("secret-pw"), credit_seconds=600), User(email="boss", password_hash=auth.hash_password("boss-pw"), is_admin=True, is_superadmin=True),
               User(email="other", password_hash=auth.hash_password("o-pw"))])
    s.commit()
    users = {u.email: u for u in s.query(User).all()}
    H = {k: {"Authorization": f"Bearer {auth.make_token(u)}"} for k, u in users.items()}
c = TestClient(main.app)
src = f"{tmp}/up/a.mp4"
open(src, "wb").write(b"x")
with Session() as s:
    s.add(Job(id="j1", user_id=users["amy"].id, status="done", params={}, data={}, input_key=src, charged_seconds=60))
    s.add(Job(id="j2", user_id=users["other"].id, status="done", params={}, data={}, input_key=f"{tmp}/up/b.mp4", charged_seconds=60))
    s.add(Preset(user_id=users["amy"].id, name="mine", settings={}))
    s.add(Preset(user_id=None, name="shared", settings={}, status="published"))
    s.add(Review(job_id="j1", user_id=users["amy"].id, user_label="amy", stars=5, text="great"))
    s.commit()

ok(c.request("DELETE", "/api/account", json={"password": "secret-pw"}).status_code in (401, 403), "needs a login")
ok(c.request("DELETE", "/api/account", json={"password": "nope"}, headers=H["amy"]).status_code == 403, "wrong password refused")
ok(os.path.exists(src) and c.post("/api/auth/login", json={"email": "amy", "username": "amy", "password": "secret-pw"}).status_code == 200, "nothing was deleted by the refusal")
ok(c.request("DELETE", "/api/account", json={"password": "boss-pw"}, headers=H["boss"]).status_code == 400, "an admin account cannot use it")
with Session() as s:
    s.add(Job(id="jr", user_id=users["amy"].id, status="running", params={}, data={}, input_key=src)); s.commit()
r = c.request("DELETE", "/api/account", json={"password": "secret-pw"}, headers=H["amy"])
ok(r.status_code == 409, "refused while a video is being made")
with Session() as s:
    s.get(Job, "jr").status = "done"; s.commit()
r = c.request("DELETE", "/api/account", json={"password": "secret-pw"}, headers=H["amy"])
ok(r.status_code == 200 and r.json()["deleted"], "deleted with the right password")
with Session() as s:
    ok(s.query(User).filter_by(email="amy").count() == 0, "account gone")
    ok(s.query(Job).filter_by(user_id=users["amy"].id).count() == 0 and s.get(Job, "j2") is not None, "her videos gone, someone else's kept")
    ok(s.query(Preset).filter_by(user_id=users["amy"].id).count() == 0 and s.query(Preset).filter_by(name="shared").count() == 1, "her presets gone, the shared one kept")
    rv = s.query(Review).filter_by(job_id="j1").one()
    ok(rv.user_label == "(deleted account)" and rv.stars == 5, "review kept without her login name")
    a = s.query(AuditLog).filter_by(action="user.self_delete").one()
    ok(a.target_label == "amy" and a.details["bought_minutes_left"] == 10.0, "audit row")
ok(not os.path.exists(src), "source file removed")
ok(c.get("/api/auth/me", headers=H["amy"]).status_code == 401, "old session stops working")
ok(c.post("/api/auth/login", json={"email": "amy", "username": "amy", "password": "secret-pw"}).status_code in (401, 403), "cannot log in again")
print("ALL OK")
