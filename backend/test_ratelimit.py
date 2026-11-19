"""Offline test: login / sign-up throttling (ratelimit.py, security audit finding 6), through the real HTTP routes with a controllable clock.
  1. One phone fumbling a password: 5 wrong tries, then refused (even with the RIGHT password) until the window passes; other phones are not affected.
  2. Normal users are never slowed down: many correct logins, and a correct login clears the account's failed tries.
  3. A botnet guessing at ONE account from many addresses: refused after 20 tries in total, whatever the address.
  4. One address trying MANY accounts: refused after 30; a refused try does not burn the account's budget.
  5. 40 parallel guesses: at most 5 reach the password check (the old limiter counted after the check).
  6. Sign-up has its own budget; login and sign-up do not use each other's.
  7. The table stays small under a flood of addresses.
  8. Unknown names cost the same work as a wrong password (no timing tell); absurdly long passwords are not hashed.
  9. "Delete my account" cannot be used to guess the password.
Run: python test_ratelimit.py"""
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", TRUST_PROXY="1", ALLOW_SIGNUP="false")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)
from fastapi.testclient import TestClient  # noqa: E402
import auth, main, ratelimit  # noqa: E402
from db import Session, User  # noqa: E402

NOW = [1_000_000.0]
ratelimit._clock = lambda: NOW[0]


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


PW = "correct-horse-1"
with Session() as s:
    for name in ("amy", "bob", "dan"):
        s.add(User(email=name, password_hash=auth.hash_password(PW), daily_minutes=30, monthly_minutes=300))
    s.commit()
    dan_token = auth.make_token(s.query(User).filter_by(email="dan").one())
c = TestClient(main.app)
calls = {"n": 0}
real_verify = auth.verify_password


def counting_verify(password, stored):
    calls["n"] += 1
    return real_verify(password, stored)


auth.verify_password = counting_verify


def login(name, pw, ip):
    return c.post("/api/auth/login", json={"email": name, "password": pw, "device_id": "device-0001"}, headers={"x-forwarded-for": ip})


def fresh():
    ratelimit.reset_all(); NOW[0] += 100_000; calls["n"] = 0


# ---- 1. one phone fumbling a password
fresh()
codes = [login("amy", "wrong-1", "10.0.0.1").status_code for _ in range(5)]
ok(codes == [401] * 5, "1. five wrong tries are answered 401 (wrong password)")
r = login("amy", PW, "10.0.0.1")
ok(r.status_code == 429 and r.json()["detail"] == "Too many attempts. Try again in a few minutes.", "1. the 6th try is refused with the old text, even with the RIGHT password")
ok(r.headers.get("retry-after", "").isdigit() and 0 < int(r.headers["retry-after"]) <= 900, f"1. Retry-After says how long ({r.headers.get('retry-after')} s)")
ok(login("amy", PW, "10.0.0.2").status_code == 200, "1. the same account from another phone still works")
ok(login("bob", PW, "10.0.0.1").status_code == 200, "1. another account from the same phone/address still works")
NOW[0] += 901
ok(login("amy", PW, "10.0.0.1").status_code == 200, "1. after 15 minutes the first phone can log in again")

# ---- 2. normal users are never slowed down
fresh()
ok(all(login("amy", PW, "10.0.0.1").status_code == 200 for _ in range(12)), "2. 12 correct logins in a row: never limited")
fresh()
for _ in range(4):
    login("amy", "wrong-1", "10.0.0.1")
ok(login("amy", PW, "10.0.0.1").status_code == 200, "2. 4 wrong tries then the right password: logged in")
ok([login("amy", "wrong-1", "10.0.0.1").status_code for _ in range(4)] == [401] * 4, "2. ...and the failed tries were cleared: 4 more wrong tries are still only 401")

# ---- 3. a botnet at one account
fresh()
codes = [login("amy", "guess", f"20.0.{i // 250}.{i % 250 + 1}").status_code for i in range(25)]
ok(codes.count(401) == 20 and codes.count(429) == 5, f"3. 25 addresses guessing at one account: only 20 tries are answered, the rest refused {codes.count(401)}/{codes.count(429)}")
ok(login("amy", PW, "99.9.9.9").status_code == 429, "3. while it lasts, a brand new address is refused too (documented trade-off)")
ok(login("bob", PW, "99.9.9.9").status_code == 200, "3. other accounts are not affected")
NOW[0] += 901
ok(login("amy", PW, "99.9.9.9").status_code == 200, "3. after 15 minutes the owner can log in")

# ---- 4. one address trying many accounts
fresh()
codes = [login(f"nobody{i}", "guess", "30.0.0.1").status_code for i in range(32)]
ok(codes.count(401) == 30 and codes.count(429) == 2, f"4. one address trying 32 different names: 30 answered, then refused {codes.count(401)}/{codes.count(429)}")
for _ in range(25):
    login("amy", "guess", "30.0.0.1")   # refused outright (the address is used up)
ok(login("amy", "guess", "31.0.0.1").status_code == 401, "4. those refused tries did not burn amy's account budget (a new address still gets a normal 401)")

# ---- 5. parallel guesses
fresh()
with ThreadPoolExecutor(max_workers=20) as pool:
    codes = list(pool.map(lambda _: login("amy", "guess", "40.0.0.1").status_code, range(40)))
ok(codes.count(401) == 5 and codes.count(429) == 35, f"5. 40 parallel guesses: exactly 5 answered, 35 refused {codes.count(401)}/{codes.count(429)}")
ok(calls["n"] == 5, f"5. only {calls['n']} of them reached the password check (the rest were stopped before the slow hash)")

# ---- 6. sign-up has its own budget
fresh()
codes = [c.post("/api/auth/register", json={"email": f"new{i}@example.com", "password": "password123"}, headers={"x-forwarded-for": "50.0.0.1"}).status_code for i in range(12)]
ok(codes.count(403) == 10 and codes.count(429) == 2, f"6. sign-up: 10 per hour per address ({codes.count(403)} answered, {codes.count(429)} refused)")
ok(login("amy", PW, "50.0.0.1").status_code == 200, "6. login from that address is not affected by the sign-up budget")
fresh()
for _ in range(5):
    login("amy", "guess", "51.0.0.1")
ok(c.post("/api/auth/register", json={"email": "x@example.com", "password": "password123"}, headers={"x-forwarded-for": "51.0.0.1"}).status_code == 403,
   "6. ...and wrong logins do not use up the sign-up budget")

# ---- 7. the table stays small
fresh()
ratelimit.MAX_KEYS = 60
for i in range(300):
    login(f"flood{i}", "guess", f"60.{i // 250}.{i % 250}.1")
ok(ratelimit._store.size() <= 70, f"7. 300 attempts from 300 addresses: the table holds {ratelimit._store.size()} keys (limit 60 + one attempt)")
NOW[0] += 5000
for i in range(30):
    login(f"later{i}", "guess", f"61.0.0.{i + 1}")
ok(ratelimit._store.size() <= 70, f"7. old keys are dropped as time passes ({ratelimit._store.size()} keys)")
ratelimit.MAX_KEYS = 20000

# ---- 8. no timing tell, no huge hashes
fresh()
login("does-not-exist", "guess", "70.0.0.1")
ok(calls["n"] == 1, "8. an UNKNOWN name still costs one full password check (against a dummy hash), like a wrong password")
calls["n"] = 0; login("amy", "wrong", "70.0.0.2")
ok(calls["n"] == 1, "8. a wrong password for a real name costs one check too")
calls["n"] = 0; r = login("amy", "x" * 5000, "70.0.0.3")
ok(r.status_code == 401 and calls["n"] == 0, "8. a 5,000-character password is refused (401) without being hashed")
ok(login("amy", PW, "70.0.0.4").status_code == 200 and login("AMY ", PW, "70.0.0.5").status_code == 200, "8. normal login (also with other capitals / spaces) still works")

# ---- 9. "delete my account" cannot be used to guess the password
fresh()
H = {"Authorization": f"Bearer {dan_token}"}
codes = [c.request("DELETE", "/api/account", json={"password": "guess"}, headers=H).status_code for _ in range(5)]
ok(codes == [403] * 5, "9. five wrong passwords on 'delete my account': 403 each")
ok(c.request("DELETE", "/api/account", json={"password": PW}, headers=H).status_code == 429, "9. the 6th try is refused (even with the right password) - a stolen session cannot guess here")
NOW[0] += 901
ok(c.request("DELETE", "/api/account", json={"password": PW}, headers=H).status_code == 200, "9. after 15 minutes the real owner can delete the account")
print("ALL OK")
