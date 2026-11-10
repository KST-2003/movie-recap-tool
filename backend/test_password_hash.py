"""Offline test: stronger password hashes with silent upgrade, and a separate key for file links (security fix).
Before: scrypt N=2^14, p=1 (about 6 times cheaper to attack than today's guidance), no way to raise the cost, and one secret for both
login tokens and signed file links.
Run: python test_password_hash.py"""
import hashlib
import hmac
import os
import secrets
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
for k in ("PASSWORD_SCRYPT_LOG2_N", "PASSWORD_SCRYPT_P", "REDIS_URL"):
    os.environ.pop(k, None)

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import manage  # noqa: E402
from db import Session, User  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def legacy_hash(password):
    """Exactly what the app wrote before: salt$digest, scrypt N=2^14 r=8 p=1, 64-byte digest."""
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1).hex()}"


# ---- 1. new hashes ----
t0 = time.time()
h1, h2 = auth.hash_password("correct horse"), auth.hash_password("correct horse")
took = (time.time() - t0) / 2
ok(h1.startswith("scrypt$15$8$3$") and len(h1) < 255, f"new format records its settings: {h1[:24]}... ({len(h1)} chars, fits the 255-char column)")
ok(h1 != h2, "same password, different hash (random salt)")
ok(auth.verify_password("correct horse", h1) and not auth.verify_password("correct horsf", h1), "right password accepted, wrong refused")
ok(not auth.verify_password("", h1), "empty password refused")
ok(took < 4.0, f"one hash takes {took:.2f}s (acceptable for a login; the limiter bounds how often it can be triggered)")
old = (2 ** 14) * 8 * 1
new = (2 ** auth.SCRYPT_LOG2_N) * auth.SCRYPT_R * auth.SCRYPT_P
ok(new >= 5 * old, f"work factor is {new / old:.0f}x the old setting")
ok(not auth.needs_rehash(h1), "a fresh hash does not need an upgrade")

# ---- 2. old hashes still work and are recognised ----
old_hash = legacy_hash("old password")
ok(auth.verify_password("old password", old_hash) and not auth.verify_password("wrong", old_hash), "an old-format hash still verifies")
ok(auth.needs_rehash(old_hash), "... and is marked for an upgrade")

# ---- 3. damaged / hostile stored values never crash and never allocate gigabytes ----
for bad in ("", "x", "$", "a$b$c", "scrypt$15$8$3$zz$zz", "scrypt$15$8$3$00$00", "scrypt$40$8$3$" + "00" * 16 + "$" + "00" * 32,
            "scrypt$15$999$3$" + "00" * 16 + "$" + "00" * 32, "scrypt$15$8$0$" + "00" * 16 + "$" + "00" * 32, "nothex$nothex"):
    ok(auth.verify_password("x", bad) is False and auth.needs_rehash(bad) is False, f"bad stored value {bad[:30]!r}: refused, no crash")

# ---- 4. the upgrade happens on login ----
client = TestClient(main.app)
with Session() as s:
    for name in ("alice", "bob"):
        s.add(User(email=f"{name}@x.com", password_hash=legacy_hash(f"{name}-password"), daily_minutes=10, monthly_minutes=10))
    s.commit()


def stored(name):
    with Session() as s:
        return s.query(User).filter(User.email == f"{name}@x.com").one().password_hash


def login(name, pw):
    return client.post("/api/auth/login", json={"email": f"{name}@x.com", "password": pw})


before = stored("alice")
r = login("alice", "alice-password")
after = stored("alice")
ok(r.status_code == 200 and not before.startswith("scrypt$") and after.startswith("scrypt$15$8$3$"), "alice logs in with her old hash and it is upgraded")
ok(login("alice", "alice-password").status_code == 200 and stored("alice") == after, "the next login works and does not rewrite it again")
ok(login("alice", "nope-nope-nope").status_code == 401, "wrong password still refused after the upgrade")
before_bob = stored("bob")
ok(login("bob", "bob-WRONG").status_code == 401 and stored("bob") == before_bob, "a WRONG password never upgrades (we only hold the password after a correct login)")

# ---- 5. every place that sets a password writes the new format ----
r = client.post("/api/auth/register", json={"email": "new@x.com", "password": "password123"})
ok(r.status_code == 200 and stored("new").startswith("scrypt$15$8$3$"), "sign-up")
with Session() as s:
    s.add(User(email="root@x.com", password_hash=auth.hash_password("root-password"), is_admin=True, daily_minutes=10, monthly_minutes=10))
    s.commit()
root = login("root", "root-password").json()["token"]
adm = {"Authorization": f"Bearer {root}"}
uid = client.get("/api/admin/users?q=bob", headers=adm).json()["items"][0]["id"]
client.patch(f"/api/admin/users/{uid}", headers=adm, json={"password": "bob-reset-pass"})
ok(stored("bob").startswith("scrypt$15$8$3$") and login("bob", "bob-reset-pass").status_code == 200, "admin password reset")
client.post("/api/admin/users", headers=adm, json={"email": "made@x.com", "password": "password123"})
ok(stored("made").startswith("scrypt$15$8$3$"), "admin creates an account")
manage.main(["create-user", "cli@x.com", "password123"])
ok(stored("cli").startswith("scrypt$15$8$3$"), "manage.py create-user")
ok(auth.DUMMY_HASH.startswith("scrypt$15$8$3$"), "the stand-in hash for unknown e-mails has the same cost (no timing difference)")

# ---- 6. raising the cost later: old-setting hashes get upgraded too ----
auth.SCRYPT_LOG2_N = 16
ok(auth.needs_rehash(stored("alice")) and auth.verify_password("alice-password", stored("alice")), "if the cost is raised, today's hashes count as old and still verify")
auth.SCRYPT_LOG2_N = 15

# ---- 7. signed file links have their own key ----
exp, sig = auth.sign_file("video.mp4", 600)
ok(auth.check_signature("video.mp4", exp, sig), "a signed link verifies")
ok(not auth.check_signature("other.mp4", exp, sig), "... only for its own file")
ok(not auth.check_signature("video.mp4", exp + 1, sig), "... and its own expiry")
ok(not auth.check_signature("video.mp4", int(time.time()) - 5, hmac.new(auth._FILE_KEY, f"video.mp4.{int(time.time()) - 5}".encode(), hashlib.sha256).hexdigest()), "an expired link is refused")
raw = hmac.new(auth.SECRET, f"video.mp4.{exp}".encode(), hashlib.sha256).hexdigest()
ok(not auth.check_signature("video.mp4", exp, raw), "a signature made with the raw login secret is NOT accepted as a file link")
ok(auth._FILE_KEY != auth.SECRET and len(auth._FILE_KEY) == 32, "the file key is derived, not the secret itself")
token = jwt.decode(login("alice", "alice-password").json()["token"], auth.SECRET, algorithms=["HS256"])
ok(token["sub"], "login tokens are still signed with the secret itself (existing sessions keep working)")
try:
    jwt.decode(login("alice", "alice-password").json()["token"], auth._FILE_KEY, algorithms=["HS256"])
    ok(False, "a login token must not verify with the file key")
except jwt.InvalidTokenError:
    ok(True, "a login token does not verify with the file-link key")

print("ALL OK")
