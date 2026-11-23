"""Offline test: request guard (guard.py): no body is read before a login on upload routes, per-route body limits (declared and streamed),
CORS headers on the guard's own answers, normal requests untouched.
Run: python test_guard.py"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", MAX_UPLOAD_MB="1")   # upload limit = 1 + 25 = 26 MB
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)
import jwt  # noqa: E402
import starlette.requests as sr  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import auth, guard, main  # noqa: E402
from db import Session, User  # noqa: E402

MB = 1024 * 1024


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


# count how often a request body is parsed (multipart / form), to prove it does NOT happen before the login on upload routes
parsed = {"n": 0}
_orig = sr.Request._get_form


async def _traced(self, *a, **k):
    parsed["n"] += 1
    return await _orig(self, *a, **k)


sr.Request._get_form = _traced

with Session() as s:
    s.add(User(email="boss", password_hash="x", is_admin=True, is_superadmin=True))
    s.add(User(email="pat", password_hash="x", daily_minutes=30, monthly_minutes=300)); s.commit()
    admin_tok = auth.make_token(s.query(User).filter_by(email="boss").one())
    user_tok = auth.make_token(s.query(User).filter_by(email="pat").one())
A, U = {"Authorization": f"Bearer {admin_tok}"}, {"Authorization": f"Bearer {user_tok}"}
c = TestClient(main.app)
BIG = b"A" * (3 * MB)   # a body that is cheap to send but would be parsed and stored if the guard did not stop it

# ---- rules table
ok(guard.rule_for("POST", "/api/jobs") == (26 * MB, True), "POST /api/jobs: video + logo limit, login first")
ok(guard.rule_for("POST", "/api/jobs/abc123/device-video")[1] is True, "device-video: login first")
ok(guard.rule_for("POST", "/api/topup/requests") == (10 * MB, True), "top-up slip route: 10 MB, login first")
ok(guard.rule_for("POST", "/api/auth/login") == (64 * 1024, False), "login: 64 KB")
ok(guard.rule_for("POST", "/api/jobs/abc/rerender") == (8 * MB, False), "everything else: 8 MB")
ok(guard.rule_for("GET", "/api/jobs") == (8 * MB, False), "GET /api/jobs is not the upload route")

# ---- 1. no login -> 401 and the body is never parsed
parsed["n"] = 0
r = c.post("/api/jobs", files={"video_file": ("a.mp4", BIG, "video/mp4")})
ok(r.status_code == 401 and r.json()["detail"] == "Please log in.", "upload without a token: 401")
ok(parsed["n"] == 0, "... and the multipart body was NOT read")
r = c.post("/api/jobs", headers={"Authorization": "Bearer not-a-token"}, files={"video_file": ("a.mp4", BIG, "video/mp4")})
ok(r.status_code == 401 and parsed["n"] == 0, "upload with a garbage token: 401, body not read")
forged = jwt.encode({"sub": "1", "exp": int(time.time()) + 3600}, "some-other-secret", algorithm="HS256")
r = c.post("/api/jobs", headers={"Authorization": f"Bearer {forged}"}, files={"video_file": ("a.mp4", BIG, "video/mp4")})
ok(r.status_code == 401 and parsed["n"] == 0, "upload with a token signed by the wrong key: 401, body not read")
expired = jwt.encode({"sub": "1", "exp": int(time.time()) - 10}, auth.SECRET, algorithm="HS256")
r = c.post("/api/jobs", headers={"Authorization": f"Bearer {expired}"}, files={"video_file": ("a.mp4", BIG, "video/mp4")})
ok(r.status_code == 401 and parsed["n"] == 0, "upload with an expired token: 401, body not read")
for path, kw in (("/api/jobs/abc/device-video", {"files": {"video": ("v.mp4", BIG, "video/mp4")}}),
                 ("/api/topup/requests", {"data": {"minutes": 30}, "files": {"slip": ("s.png", BIG, "image/png")}}),
                 ("/api/admin/payment-qr", {"files": {"file": ("q.png", BIG, "image/png")}}),
                 ("/api/admin/posts", {"files": {"image": ("p.png", BIG, "image/png")}})):
    parsed["n"] = 0
    r = c.post(path, **kw)
    ok(r.status_code == 401 and parsed["n"] == 0, f"{path} without a token: 401, body not read")

# ---- 2. declared size too large
r = c.post("/api/auth/login", content=b"x" * (70 * 1024), headers={"content-type": "application/json"})
ok(r.status_code == 413 and "too large" in r.json()["detail"], "login body of 70 KB: 413")
r = c.post("/api/auth/login", json={"email": "pat", "password": "x" * 200_000})
ok(r.status_code == 413, "login with a 200 KB password: 413 (was: parsed and hashed)")
r = c.post("/api/jobs/abc/rerender", headers=U, content=b"x" * (9 * MB), )
ok(r.status_code == 413, "re-render JSON of 9 MB: 413")
r = c.post("/api/jobs", headers=U, files={"video_file": ("a.mp4", b"A" * (27 * MB), "video/mp4")})
ok(r.status_code == 413 and "26 MB" in r.json()["detail"], "upload over the limit (declared length): 413 with the limit named")
ok(not os.listdir(f"{tmp}/up") or all(not f.endswith(".mp4") for f in os.listdir(f"{tmp}/up")), "... nothing was stored")

# ---- 3. a body that does not declare its size (chunked) is counted while it streams
def chunks(total, piece=64 * 1024):
    sent = 0
    while sent < total:
        n = min(piece, total - sent)
        sent += n
        yield b"x" * n
r = c.post("/api/auth/login", content=chunks(10 * MB), headers={"content-type": "application/json"})
ok(r.status_code == 413, "chunked login body of 10 MB: cut off, 413")
r = c.post("/api/jobs/abc/rerender", headers=U, content=chunks(20 * MB), )
ok(r.status_code == 413, "chunked 20 MB JSON: cut off, 413")
r = c.post("/api/jobs", headers={**U, "content-type": "multipart/form-data; boundary=zz"}, content=chunks(40 * MB))
ok(r.status_code == 413, "chunked upload of 40 MB (over 26 MB): cut off, 413")

# ---- 4. the guard's own answers carry CORS headers (the browser shows the message, not a network error)
origin = {"Origin": "http://localhost:3000"}
r = c.post("/api/jobs", headers=origin, files={"video_file": ("a.mp4", b"x", "video/mp4")})
ok(r.status_code == 401 and r.headers.get("access-control-allow-origin") == "http://localhost:3000", "401 from the guard has CORS headers")
r = c.post("/api/auth/login", headers={**origin, "content-type": "application/json"}, content=b"x" * (70 * 1024))
ok(r.status_code == 413 and r.headers.get("access-control-allow-origin") == "http://localhost:3000", "413 from the guard has CORS headers")

# ---- 5. normal requests are untouched
r = c.post("/api/auth/login", json={"email": "nobody", "password": "password123", "device_id": "device-0001"})
ok(r.status_code == 401 and r.json()["detail"] == "Wrong username or password.", "a normal login attempt reaches the route")
parsed["n"] = 0
r = c.post("/api/jobs", headers=U, files={"video_file": ("a.mp4", b"not a video", "video/mp4")})
ok(r.status_code == 400 and "valid video" in r.json()["detail"] and parsed["n"] == 1, "a logged-in upload is read and reaches the route (400: not a real video)")
r = c.post("/api/jobs", headers=U, files={"video_file": ("a.mp4", b"A" * (5 * MB), "video/mp4")})
ok(r.status_code == 413 and r.json()["detail"] == "File is larger than 1 MB.", "a 5 MB upload is under the guard's 26 MB: the ROUTE reads it and applies its own 1 MB video limit")
ok(c.get("/api/auth/me", headers=U).status_code == 200, "GET with a token works")
ok(c.get("/health").json() == {"ok": True}, "GET without a token works")
r = c.post("/api/jobs/abc/rerender", headers=U, json={"segments": [{"id": 0, "start": 0, "text": "x"}]})
ok(r.status_code == 404, "a normal re-render request reaches the route (404: unknown job)")
ok(c.options("/api/jobs", headers={**origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"}).status_code == 200,
   "CORS preflight for the upload route is not blocked by the guard")
print("ALL OK")
