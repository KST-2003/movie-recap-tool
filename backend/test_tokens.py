"""Offline test: login tokens are revocable and admin tokens are short (security fix).
Before: every token lived 14 days (admins too), a password reset / disable / demotion did not cancel tokens already issued, and
re-enabling a disabled account brought its old tokens back.
Run: python test_tokens.py"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
os.environ.pop("REDIS_URL", None)

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from db import Session, User  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


client = TestClient(main.app)
PW = "correct-horse"
ids = {}
with Session() as s:
    for name, admin in (("root", True), ("alice", False), ("bob", False), ("carol", False)):
        u = User(email=f"{name}@x.com", password_hash=auth.hash_password(PW), daily_minutes=10, monthly_minutes=10, is_admin=admin)
        s.add(u)
        s.commit()
        ids[name] = u.id


def login(name, password=PW):
    r = client.post("/api/auth/login", json={"email": f"{name}@x.com", "password": password})
    assert r.status_code == 200, (name, r.status_code, r.text)
    return r.json()["token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def me(token):
    return client.get("/api/auth/me", headers=bearer(token)).status_code


def claims(token):
    return jwt.decode(token, auth.SECRET, algorithms=["HS256"])


def patch(user, **body):
    return client.patch(f"/api/admin/users/{ids[user]}", headers=bearer(root), json=body)


def forge(sub, **extra):
    now = int(time.time())
    payload = {"sub": str(sub), "exp": now + 600, **extra}
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, auth.SECRET, algorithm="HS256")


# ---- 1. lifetimes ----
root = login("root")
alice = login("alice")
c_root, c_alice = claims(root), claims(alice)
ok(c_root["exp"] - c_root["iat"] == 3600, f"admin token lives 60 minutes ({c_root['exp'] - c_root['iat']}s)")
ok(c_alice["exp"] - c_alice["iat"] == 14 * 86400, "normal user token lives 14 days")
ok(c_root["tv"] == 0 and c_root["ses"] == c_root["iat"], "token carries its version and session start")
ok(me(root) == me(alice) == 200, "both tokens work")
ok(me(forge(ids["alice"])) == 200, "a token issued before this change (no version claim) keeps working until the account is revoked")

# ---- 2. admin resets a password: that account is signed out everywhere ----
alice2 = login("alice")
bob = login("bob")
r = patch("alice", password="brand-new-pass")
ok(r.status_code == 200, "admin resets alice's password")
ok(me(alice) == 401 and me(alice2) == 401, "both of alice's old tokens are dead")
ok(me(bob) == 200, "bob's token is untouched")
ok(client.post("/api/auth/login", json={"email": "alice@x.com", "password": PW}).status_code == 401, "old password refused")
alice = login("alice", "brand-new-pass")
ok(me(alice) == 200, "new login works")

# ---- 3. disable then enable: old tokens do not come back ----
old = alice
patch("alice", is_active=False)
ok(me(old) == 401, "disabled: token refused")
patch("alice", is_active=True)
ok(me(old) == 401, "re-enabled: the OLD token is still dead (it used to start working again)")
alice = login("alice", "brand-new-pass")
ok(me(alice) == 200, "a fresh login works")

# ---- 4. promote / demote: privileges never ride on an old token ----
old_bob = bob
r = patch("bob", is_admin=True)
ok(r.status_code == 200 and me(old_bob) == 401, "promoted: the old long-lived token is dead")
bob = login("bob")
c = claims(bob)
ok(c["exp"] - c["iat"] == 3600, "a promoted account gets short admin tokens")
ok(client.get("/api/admin/overview", headers=bearer(bob)).status_code == 200, "and can use the admin API")
r = patch("bob", is_admin=False)
ok(me(bob) == 401 and client.get("/api/admin/overview", headers=bearer(bob)).status_code == 401, "demoted: the admin token is dead")
bob = login("bob")
ok(client.get("/api/admin/overview", headers=bearer(bob)).status_code == 403, "demoted account sees 403 on the admin API")

# ---- 5. log out everywhere ----
a1, a2, b1 = login("alice", "brand-new-pass"), login("alice", "brand-new-pass"), login("bob")
ok(client.post("/api/auth/logout-all", headers=bearer(a1)).status_code == 200, "alice presses 'log out everywhere'")
ok(me(a1) == 401 and me(a2) == 401, "all of alice's sessions are dead")
ok(me(b1) == 200, "bob's session is untouched")
ok(client.post("/api/auth/logout-all").status_code == 401, "logout-all needs a login")

# ---- 6. an admin changing their OWN password signs themselves out ----
root2 = login("root")
carol = login("carol")
patch_self = client.patch(f"/api/admin/users/{ids['root']}", headers=bearer(root2), json={"password": "root-new-pass"})
ok(patch_self.status_code == 200 and me(root2) == 401, "changing your own password ends your current sessions")
root = login("root", "root-new-pass")

# ---- 7. renewing ----
r = client.post("/api/auth/refresh", headers=bearer(root))
new = r.json()["token"]
ok(r.status_code == 200 and claims(new)["ses"] == claims(root)["ses"] and claims(new)["tv"] == claims(root)["tv"], "refresh gives a new token with the same session start and version")
ok(me(new) == 200, "the renewed token works")
ok(client.post("/api/auth/refresh").status_code == 401, "refresh needs a token")
carol_old = carol
client.post("/api/auth/logout-all", headers=bearer(carol))
ok(client.post("/api/auth/refresh", headers=bearer(carol_old)).status_code == 401, "a revoked token cannot be renewed")
admin_old_session = forge(ids["root"], tv=claims(root)["tv"], ses=int(time.time()) - 13 * 3600)
ok(client.post("/api/auth/refresh", headers=bearer(admin_old_session)).status_code == 401, "admin session older than 12 hours cannot be renewed (must type the password again)")
ok(me(admin_old_session) == 200, "... though the token itself still works until it expires")
user_old_session = forge(ids["bob"], tv=claims(bob)["tv"], ses=int(time.time()) - 61 * 86400)
ok(client.post("/api/auth/refresh", headers=bearer(user_old_session)).status_code == 401, "a normal session older than 60 days cannot be renewed")
fresh_session = forge(ids["bob"], tv=claims(bob)["tv"], ses=int(time.time()) - 30 * 86400)
ok(client.post("/api/auth/refresh", headers=bearer(fresh_session)).status_code == 200, "a 30-day-old normal session can")

# ---- 8. bad tokens ----
now = int(time.time())
ok(me(jwt.encode({"sub": str(ids["bob"]), "exp": now - 5}, auth.SECRET, algorithm="HS256")) == 401, "expired token refused")
ok(me(jwt.encode({"sub": str(ids["bob"])}, auth.SECRET, algorithm="HS256")) == 401, "a token with no expiry refused")
ok(me(jwt.encode({"sub": str(ids["bob"]), "exp": now + 600}, "some-other-secret-key-of-32-bytes!!", algorithm="HS256")) == 401, "token signed with another key refused")
ok(me(jwt.encode({"sub": str(ids["bob"]), "exp": now + 600}, None, algorithm="none")) == 401, "unsigned (alg none) token refused")
ok(me(forge("not-a-number")) == 401, "non-numeric subject refused")
ok(me(forge(99999)) == 401, "token for a user that does not exist refused")
good = login("bob")
head, body, sig = good.split(".")
ok(me(f"{head}.{body}.{sig[:-3]}abc") == 401, "tampered signature refused")
ok(me("garbage") == 401, "garbage refused")

# ---- 9. the command line tool also revokes ----
import manage  # noqa: E402
t = login("carol")
manage.main(["deactivate", "carol@x.com"])
manage.main(["activate", "carol@x.com"])
ok(me(t) == 401, "manage.py deactivate/activate also cancels old tokens")

print("ALL OK")
