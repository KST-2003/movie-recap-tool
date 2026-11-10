"""Offline test: the request guard (body limits, login before upload bodies, admin allow-list, security headers).
The tests talk to the app at ASGI level so they can count exactly how many body bytes the server read before it answered.
Run: python test_request_guard.py"""
import asyncio
import itertools
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
for k in ("ADMIN_ALLOWED_IPS", "TRUSTED_PROXIES", "REDIS_URL"):
    os.environ.pop(k, None)

import jwt  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import guard  # noqa: E402
import main  # noqa: E402
from db import Session, User  # noqa: E402

main.jobs_queue.enqueue = lambda job_id: None
main.upload_duration = lambda path: 60.0

MB = 1024 * 1024


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    alice = User(email="alice@x.com", password_hash=auth.hash_password("pw-pw-pw-pw"), daily_minutes=100, monthly_minutes=1000)
    root = User(email="root@x.com", password_hash=auth.hash_password("pw-pw-pw-pw"), daily_minutes=100, monthly_minutes=1000, is_admin=True)
    s.add_all([alice, root])
    s.commit()
TOKEN = auth.make_token(alice)
ROOT = auth.make_token(root)


def chunks(n_mb):
    block = b"x" * MB
    for _ in range(n_mb):
        yield block


def asgi(method, path, body=b"", stream=None, headers=None, client=("203.0.113.5", 4000), content_length=None):
    """Call the app directly. -> (status, response headers, response body, bytes of request body the app pulled)."""
    pulled = 0
    source = iter(stream) if stream is not None else iter([body] if body else [])

    async def receive():
        nonlocal pulled
        try:
            piece = next(source)
            pulled += len(piece)
            return {"type": "http.request", "body": piece, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    sent = []

    async def send(message):
        sent.append(message)

    hdrs = dict(headers or {})
    if content_length is not None:
        hdrs["content-length"] = str(content_length)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "root_path": "", "scheme": "http", "client": client, "server": ("test", 80),
             "headers": [(k.lower().encode(), v.encode()) for k, v in hdrs.items()]}
    asyncio.run(main.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    resp_headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    resp_body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], resp_headers, resp_body, pulled


bearer = {"authorization": f"Bearer {TOKEN}"}

# ---- 1. an upload needs a login BEFORE its body is read ----
st, h, body, pulled = asgi("POST", "/api/jobs", stream=chunks(200), headers={"content-type": "multipart/form-data; boundary=x"})
ok(st == 401 and pulled == 0, f"no login: 401 and the server read {pulled} of 200 MB")
st, _, _, pulled = asgi("POST", "/api/jobs", stream=chunks(200), headers={"content-type": "multipart/form-data; boundary=x", "authorization": "Bearer garbage"})
ok(st == 401 and pulled == 0, f"garbage token: 401, read {pulled} bytes")
forged = jwt.encode({"sub": "1", "exp": 4102444800}, "another-secret-another-secret-123456", algorithm="HS256")
st, _, _, pulled = asgi("POST", "/api/jobs", stream=chunks(50), headers={"authorization": f"Bearer {forged}"})
ok(st == 401 and pulled == 0, "token signed with another key: 401, nothing read")
expired = jwt.encode({"sub": "1", "exp": 1000}, auth.SECRET, algorithm="HS256")
st, _, _, pulled = asgi("POST", "/api/jobs", stream=chunks(50), headers={"authorization": f"Bearer {expired}"})
ok(st == 401 and pulled == 0, "expired token: 401, nothing read")

# ---- 2. body size ----
guard.UPLOAD_LIMIT = 3 * MB
st, h, body, pulled = asgi("POST", "/api/jobs", stream=chunks(1), headers=bearer, content_length=5000 * MB)
ok(st == 413 and pulled == 0, f"Content-Length of 5 GB: 413 at once, read {pulled} bytes")
multipart = {**bearer, "content-type": "multipart/form-data; boundary=x"}
opening = b'--x\r\nContent-Disposition: form-data; name="video_file"; filename="a.mp4"\r\nContent-Type: video/mp4\r\n\r\n'
st, h, body, pulled = asgi("POST", "/api/jobs", stream=itertools.chain([opening], chunks(500)), headers=multipart)   # a well-formed upload that never ends, no Content-Length
ok(st == 413 and pulled <= 4 * MB, f"500 MB chunked body, limit 3 MB: 413 after reading {pulled / MB:.0f} MB")
ok(b"too large" in body, "the answer is plain JSON")
guard.UPLOAD_LIMIT = (main.MAX_UPLOAD_MB + 25) * MB
st, _, _, pulled = asgi("POST", "/api/auth/login", stream=chunks(1), content_length=100 * 1024, headers={"content-type": "application/json"})
ok(st == 413 and pulled == 0, "a 100 KB login body: 413 (login bodies are tiny)")
st, _, _, pulled = asgi("POST", "/api/jobs/abc/rerender", stream=chunks(50), headers=bearer)
ok(st == 413 and pulled <= 5 * MB, f"a 50 MB JSON body: 413 after {pulled / MB:.0f} MB")
ok(guard.UPLOAD_LIMIT == (1024 + 25) * MB, "the upload limit is MAX_UPLOAD_MB + 25 MB room for the logo")

# normal traffic still works
client = TestClient(main.app)
r = client.post("/api/auth/login", json={"email": "alice@x.com", "password": "pw-pw-pw-pw"})
ok(r.status_code == 200, "a normal login works")
r = client.post("/api/jobs", headers={"Authorization": f"Bearer {TOKEN}"}, files={"video_file": ("a.mp4", b"x" * 1000, "video/mp4")}, data={"output": "subtitles"})
ok(r.status_code == 200, f"a normal upload works ({r.status_code})")
r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {TOKEN}"})
ok(r.status_code == 200, "a normal GET works")

# ---- 3. the refusals still carry CORS headers (else the browser only shows "network error") ----
r = client.post("/api/jobs", headers={"Origin": "http://localhost:3000"})
ok(r.status_code == 401 and r.headers.get("access-control-allow-origin") == "http://localhost:3000", "401 from the guard has the CORS header")
r = client.post("/api/auth/login", headers={"Origin": "http://localhost:3000", "content-length": str(10 * MB)}, content=b"{}")
ok(r.status_code in (400, 413) and r.headers.get("access-control-allow-origin") == "http://localhost:3000", f"a refused oversized request has the CORS header too ({r.status_code})")

# ---- 4. admin allow-list ----
st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}"}, client=("8.8.8.8", 1))
ok(st == 200, "no allow-list: the admin API works from anywhere")
os.environ["ADMIN_ALLOWED_IPS"] = "10.1.2.3, 192.168.0.0/16"
st, _, body, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}"}, client=("8.8.8.8", 1))
ok(st == 404 and b"Not found" in body, "allow-list set: another address gets 404 (even with a valid admin token)")
for ip in ("10.1.2.3", "192.168.7.7"):
    st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}"}, client=(ip, 1))
    ok(st == 200, f"{ip}: allowed")
st, _, _, _ = asgi("GET", "/api/admin/users", client=("8.8.8.8", 1))
ok(st == 404, "no token + wrong address: 404 (nothing revealed)")
st, _, _, _ = asgi("GET", "/api/auth/me", headers=bearer, client=("8.8.8.8", 1))
ok(st == 200, "the normal API is not affected by the admin allow-list")
os.environ["TRUSTED_PROXIES"] = "10.0.0.0/8"
st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}", "x-forwarded-for": "192.168.1.9"}, client=("10.0.0.1", 1))
ok(st == 200, "behind a trusted proxy the forwarded client address is checked")
st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}", "x-forwarded-for": "192.168.1.9"}, client=("8.8.8.8", 1))
ok(st == 404, "a forged X-Forwarded-For from an untrusted address does not help")
st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}", "x-forwarded-for": "8.8.4.4"}, client=("10.0.0.1", 1))
ok(st == 404, "a trusted proxy forwarding an outside address: 404")
os.environ.pop("TRUSTED_PROXIES")
os.environ["ADMIN_ALLOWED_IPS"] = "not-an-ip"
st, _, _, _ = asgi("GET", "/api/admin/overview", headers={"authorization": f"Bearer {ROOT}"}, client=("8.8.8.8", 1))
ok(st == 200, "an unusable setting is ignored with a log line, it does not lock the owner out")
os.environ.pop("ADMIN_ALLOWED_IPS")


# ---- 5. response headers ----
@main.app.get("/api/_cached")
def _cached():
    return PlainTextResponse("hello", headers={"Cache-Control": "public, max-age=604800"})


@main.app.get("/api/_media")
def _media():
    return PlainTextResponse("not json", media_type="video/mp4")


r = client.post("/api/auth/login", json={"email": "alice@x.com", "password": "pw-pw-pw-pw"})
ok(r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("referrer-policy") == "no-referrer" and r.headers.get("x-frame-options") == "DENY",
   "API answers: nosniff, no referrer, no framing")
ok(r.headers.get("cache-control") == "no-store", "a login answer (it holds a token) is never cached")
ok("default-src 'none'" in r.headers.get("content-security-policy", ""), "JSON answers carry a deny-all CSP")
r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {TOKEN}"})
ok(r.headers.get("cache-control") == "no-store", "account data: no-store")
r = client.get("/api/usage", headers={"Authorization": f"Bearer {TOKEN}"})
ok(r.headers.get("cache-control") == "no-store", "usage data: no-store")
r = client.get("/api/_cached")
ok(r.headers.get("cache-control") == "public, max-age=604800", "a cache header the endpoint sets itself is left alone")
r = client.get("/api/_media")
ok("content-security-policy" not in r.headers and r.headers.get("x-content-type-options") == "nosniff", "non-JSON (video / audio) answers get no CSP, so a player opened directly still works")
r = client.get("/docs")
ok(r.status_code == 200 and "content-security-policy" not in r.headers, "the interactive docs page is untouched")
r = client.get("/api/voices")
ok(r.status_code == 200 and r.headers.get("cache-control") != "no-store", "public lists (voices) can still be cached")

print("ALL OK")
