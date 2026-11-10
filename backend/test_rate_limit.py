"""Offline test: login / signup rate limits (security fix). Memory store always; Redis store when TEST_REDIS_URL is set
(e.g.  docker run --rm -d -p 63790:6379 redis:7-alpine   then   TEST_REDIS_URL=redis://127.0.0.1:63790/0 python test_rate_limit.py).
Run: python test_rate_limit.py"""
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
os.environ.pop("TRUSTED_PROXIES", None)
os.environ.pop("REDIS_URL", None)

from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
import ratelimit  # noqa: E402
from api import accounts as api_accounts  # noqa: E402
from db import Session, User  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def fake_request(peer="203.0.113.7", xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 5555), "method": "POST", "path": "/"})


def fresh():
    ratelimit._memory = ratelimit.MemoryStore()


# ================= 1. the memory store =================
st = ratelimit.MemoryStore()
ok([st.take("k", 3, 60) for _ in range(3)] == [0, 0, 0], "first 3 attempts allowed")
wait = st.take("k", 3, 60)
ok(0 < wait <= 61, f"4th refused, told to wait {wait}s")
ok(st.take("k", 3, 60) > 0, "still refused (a refused attempt does not extend the lock)")
st.refund("k")
ok(st.take("k", 3, 60) == 0, "refund gives one attempt back")
st.reset("k")
ok(st.take("k", 3, 60) == 0, "reset clears the key")
st2 = ratelimit.MemoryStore()
st2.take("short", 1, 1)
ok(st2.take("short", 1, 1) > 0, "limit reached")
time.sleep(1.1)
ok(st2.take("short", 1, 1) == 0, "window passes, attempts allowed again")
small = ratelimit.MemoryStore(max_keys=100)
for i in range(1000):
    small.take(f"ip:{i}", 5, 900)
ok(len(small._hits) <= 200, f"the table cannot grow without bound ({len(small._hits)} keys after 1000 different addresses)")
with ThreadPoolExecutor(max_workers=16) as ex:
    res = list(ex.map(lambda _: ratelimit.MemoryStore.take(st, "par", 5, 60), range(60)))
ok(res.count(0) == 5, f"60 parallel attempts, limit 5: {res.count(0)} allowed")

# ================= 2. who is calling (proxy header handling) =================
ok(ratelimit.client_ip(fake_request("203.0.113.7", "6.6.6.6")) == "203.0.113.7", "no TRUSTED_PROXIES: X-Forwarded-For is ignored (cannot be spoofed)")
os.environ["TRUSTED_PROXIES"] = "10.0.0.0/8, 172.16.0.5"
ok(ratelimit.client_ip(fake_request("10.0.0.1", "198.51.100.9")) == "198.51.100.9", "request from the proxy: the forwarded client address is used")
ok(ratelimit.client_ip(fake_request("10.0.0.1", "9.9.9.9, 198.51.100.9")) == "198.51.100.9", "a client-written left-most entry is ignored (right-most untrusted wins)")
ok(ratelimit.client_ip(fake_request("10.0.0.1", "198.51.100.9, 10.0.0.2")) == "198.51.100.9", "several proxies in a row")
ok(ratelimit.client_ip(fake_request("203.0.113.7", "198.51.100.9")) == "203.0.113.7", "a caller that is not a trusted proxy cannot set its address")
ok(ratelimit.client_ip(fake_request("10.0.0.1", "not-an-ip")) == "10.0.0.1", "garbage header: fall back to the proxy address")
ok(ratelimit.client_ip(fake_request("10.0.0.1")) == "10.0.0.1", "no header: the proxy address")
os.environ.pop("TRUSTED_PROXIES")

# ================= 3. the API =================
api_accounts.ALLOW_SIGNUP = True   # register() reads this name from api/accounts.py now, not main.py
client = TestClient(main.app)
with Session() as s:
    for n in ("alice", "bob", "carol"):
        s.add(User(email=f"{n}@x.com", password_hash=auth.hash_password("correct-horse"), daily_minutes=10, monthly_minutes=10))
    s.commit()


def login(email, password="wrong-password"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


fresh()
codes = [login("alice@x.com").status_code for _ in range(5)]
ok(codes == [401] * 5, f"5 wrong passwords: all just 401 ({codes})")
r = login("alice@x.com")
ok(r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "minute" in r.json()["detail"], f"6th: 429 + Retry-After {r.headers.get('retry-after')}s: {r.json()['detail']}")
ok(login("alice@x.com", "correct-horse").status_code == 429, "even the right password is refused while locked")
ok(login("bob@x.com", "correct-horse").status_code == 200, "another account from the same address is not locked")

fresh()
ok(all(login("alice@x.com", "correct-horse").status_code == 200 for _ in range(40)), "40 successful logins in a row are never limited (the old limiter stopped at 10)")
fresh()
for _ in range(4):
    login("alice@x.com")
ok(login("alice@x.com", "correct-horse").status_code == 200, "4 mistakes then the right password: in")
codes = [login("alice@x.com").status_code for _ in range(4)]
ok(codes == [401] * 4, "a success clears the failure counter: 4 more mistakes are allowed again")

fresh()
codes = [login(f"nobody{i}@x.com").status_code for i in range(31)]
ok(codes[:30] == [401] * 30 and codes[30] == 429, f"one address guessing 31 different accounts: stopped at the 31st ({codes.count(401)} x 401, {codes.count(429)} x 429)")

fresh()
for i in range(20):   # 20 different addresses, 1 try each, same account (distributed guessing)
    ratelimit.login_attempt(fake_request(f"198.51.100.{i + 1}"), "alice@x.com")
try:
    ratelimit.login_attempt(fake_request("198.51.100.200"), "alice@x.com")
    ok(False, "21st address should be refused")
except Exception as exc:
    ok(getattr(exc, "status_code", None) == 429, "one account guessed from 21 different addresses: the 21st is refused")
ratelimit.login_attempt(fake_request("198.51.100.201"), "bob@x.com")
ok(True, "... but other accounts are fine")

fresh()
with ThreadPoolExecutor(max_workers=20) as ex:
    codes = list(ex.map(lambda _: login("alice@x.com").status_code, range(40)))
ok(codes.count(401) == 5 and codes.count(429) == 35, f"40 parallel guesses at one account: only {codes.count(401)} get checked, {codes.count(429)} refused")

fresh()
calls = []
real_verify = auth.verify_password
auth.verify_password = lambda pw, stored: (calls.append(stored), real_verify(pw, stored))[1]
r1 = login("nobody@x.com")
r2 = login("alice@x.com")
auth.verify_password = real_verify
ok(r1.status_code == r2.status_code == 401 and r1.json() == r2.json(), "unknown email and wrong password give the identical answer")
ok(len(calls) == 2 and calls[0] == auth.DUMMY_HASH, "an unknown email still pays for a password check (no guessing accounts by timing)")
calls.clear()
auth.verify_password = lambda pw, stored: calls.append(1)
r = login("alice@x.com", "x" * 5000)
auth.verify_password = real_verify
ok(r.status_code == 400 and not calls, "a 5000-character password is refused before any hashing")

fresh()
codes = [client.post("/api/auth/register", json={"email": f"new{i}@x.com", "password": "password123"}).status_code for i in range(12)]
ok(codes[:10] == [200] * 10 and codes[10:] == [429, 429], f"signups: 10 per hour per address, then 429 ({codes.count(200)} ok)")
ok(login("alice@x.com", "correct-horse").status_code == 200, "signup attempts and logins have separate budgets")

# ================= 4. the Redis store (only when a Redis is available) =================
url = os.getenv("TEST_REDIS_URL")
if not url:
    print("SKIP Redis checks (set TEST_REDIS_URL to run them)")
else:
    from redis import Redis
    Redis.from_url(url).flushdb()
    rs = ratelimit.RedisStore(url)
    key = f"redis-test-{time.time()}"
    ok([rs.take(key, 3, 60) for _ in range(3)] == [0, 0, 0], "redis: first 3 attempts allowed")
    wait = rs.take(key, 3, 60)
    ok(0 < wait <= 60, f"redis: 4th refused, wait {wait}s")
    ok(rs.take(key, 3, 60) > 0, "redis: still refused")
    ok(0 < Redis.from_url(url).ttl(rs._k(key)) <= 60, "redis: the counter always has an expiry")
    rs.refund(key)
    ok(rs.take(key, 3, 60) == 0, "redis: refund gives one attempt back")
    rs.reset(key)
    ok(rs.take(key, 3, 60) == 0, "redis: reset clears it")
    short = f"short-{time.time()}"
    rs.take(short, 1, 1)
    ok(rs.take(short, 1, 1) > 0, "redis: limit reached")
    time.sleep(1.2)
    ok(rs.take(short, 1, 1) == 0, "redis: key expires, attempts allowed again")
    pk = f"par-{time.time()}"
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(lambda _: rs.take(pk, 5, 60), range(60)))
    ok(res.count(0) == 5, f"redis: 60 parallel attempts, limit 5: {res.count(0)} allowed")
    other = ratelimit.RedisStore(url)   # a second API process sees the same counters
    ok(other.take(pk, 5, 60) > 0, "redis: a second process shares the counters")
    ok("redis-test" not in " ".join(k.decode() for k in Redis.from_url(url).keys("*")), "redis: keys are hashed (no e-mail addresses stored)")

    # through the module, with REDIS_URL set
    ratelimit.REDIS_URL, ratelimit._redis, ratelimit._redis_failed_at = url, None, 0.0
    Redis.from_url(url).flushdb()
    codes = [login("alice@x.com").status_code for _ in range(6)]
    ok(codes == [401] * 5 + [429], f"redis: the API limits through Redis ({codes})")
    ok(login("bob@x.com", "correct-horse").status_code == 200, "redis: other accounts unaffected")

# ================= 5. Redis down: fall back to memory, never to "no limit" and never to a 500 =================
fresh()
ratelimit.REDIS_URL, ratelimit._redis, ratelimit._redis_failed_at = "redis://127.0.0.1:1/0", None, 0.0
t0 = time.time()
codes = [login("alice@x.com").status_code for _ in range(6)]
ok(codes == [401] * 5 + [429], f"Redis unreachable: still limited, from memory ({codes})")
ok(time.time() - t0 < 15, f"... and it does not retry the dead Redis on every request ({time.time() - t0:.1f}s for 6 logins)")

print("ALL OK")
