"""Offline test: browser sessions live in an httpOnly cookie with CSRF protection (security fix: the login token was in localStorage, readable by any script
injected into the page). Bearer tokens (API clients) keep working.
Run: python test_cookie_sessions.py"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0", GCP_PROJECT_ID="",
                  GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="", CORS_ORIGINS="http://localhost:3000,http://localhost:3001",
                  ADMIN_ORIGINS="http://localhost:3001", SIGNUP_MAX_PER_DAY="0")
for k in ("REDIS_URL", "TRUSTED_PROXIES", "COOKIE_SECURE", "COOKIE_SAMESITE"):
    os.environ.pop(k, None)

import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from api import jobs as api_jobs  # noqa: E402
import ratelimit  # noqa: E402
from db import Job, Session, User  # noqa: E402

api_jobs.jobs_queue.enqueue = lambda job_id: None
api_jobs.upload_duration = lambda path: 60.0
api_jobs.MAX_ACTIVE_JOBS_PER_USER = 1000


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


APP = "http://localhost:3000"
ADM = "http://localhost:3001"
EVIL = "https://evil.example"
APP_H = {"Origin": APP}
ADM_H = {"Origin": ADM, "X-Audience": "admin"}
PW = "correct-horse"
ids = {}
with Session() as s:
    for name, admin in (("alice", False), ("bob", False), ("root", True)):
        u = User(email=f"{name}@x.com", password_hash=auth.hash_password(PW), daily_minutes=100, monthly_minutes=1000, is_admin=admin)
        s.add(u)
        s.commit()
        ids[name] = u.id


def new_client(**kw):
    return TestClient(main.app, **kw)


def login(client, name, headers=APP_H, audience="app", cookie=True, password=PW):
    ratelimit._memory = ratelimit.MemoryStore()
    return client.post("/api/auth/login", headers=headers, json={"email": f"{name}@x.com", "password": password, "audience": audience, "cookie": cookie})


def csrf_hdr(csrf, base=APP_H):
    return {**base, "X-CSRF-Token": csrf}


# ================= 1. what a cookie login looks like =================
c = new_client()
r = login(c, "alice")
set_cookie = r.headers.get("set-cookie", "")
body = r.json()
jwt_value = c.cookies.get("session")
ok(r.status_code == 200 and "token" not in body and body.get("csrf_token"), "login with cookie=true: no token in the body, a CSRF token instead")
ok(jwt_value and jwt_value not in r.text, "the session token appears nowhere in the response body (a script cannot read it)")
ok("HttpOnly" in set_cookie and "SameSite=strict" in set_cookie and "Path=/api" in set_cookie and set_cookie.startswith("session="), f"cookie flags: {set_cookie.split(';', 1)[1].strip()[:70]}...")
ok("Secure" not in set_cookie, "plain http (local development): no Secure flag, or the browser would drop the cookie")
age = int(set_cookie.split("Max-Age=")[1].split(";")[0])
ok(age == 14 * 86400, f"the cookie lives as long as the token ({age // 86400} days for a normal account)")
ok(r.headers.get("cache-control") == "no-store", "the answer is never cached")
ok(c.cookies.get("admin_session") is None, "no admin cookie for a normal login")

secure = new_client(base_url="https://testserver")
ok("Secure" in login(secure, "alice").headers["set-cookie"], "over HTTPS the cookie is Secure")
auth.COOKIE_SECURE = "0"
ok("Secure" not in login(secure, "alice").headers["set-cookie"], "COOKIE_SECURE=0 can switch it off")
auth.COOKIE_SECURE = "1"
ok("Secure" in login(new_client(), "alice").headers["set-cookie"], "COOKIE_SECURE=1 forces it on")
auth.COOKIE_SECURE = "auto"


def fake(peer, proto=None, scheme="http"):
    headers = [(b"x-forwarded-proto", proto.encode())] if proto else []
    return Request({"type": "http", "scheme": scheme, "headers": headers, "client": (peer, 1), "method": "GET", "path": "/", "server": ("t", 80)})


os.environ["TRUSTED_PROXIES"] = "10.0.0.0/8"
ok(ratelimit.is_https(fake("10.0.0.1", "https")) and not ratelimit.is_https(fake("10.0.0.1", "http")), "behind a trusted proxy that says https: Secure")
ok(not ratelimit.is_https(fake("203.0.113.9", "https")), "a caller that is not a trusted proxy cannot claim https")
os.environ.pop("TRUSTED_PROXIES")

# ================= 2. the cookie authenticates =================
r = c.get("/api/auth/me", headers=APP_H)
ok(r.status_code == 200 and r.json()["email"] == "alice@x.com", "GET /me works with the cookie alone")
csrf = r.json()["csrf_token"]
ok(csrf == body["csrf_token"], "/me hands out the same CSRF token again (after a page reload the in-memory copy is gone)")
ok(new_client().get("/api/auth/me", headers=APP_H).status_code == 401, "no cookie, no bearer: 401")

# ================= 3. CSRF =================
cancel = "/api/jobs/does-not-exist/cancel"   # passes authentication, then 404 "Unknown job"
r = c.post(cancel, headers=APP_H)
ok(r.status_code == 403 and "Security check" in r.json()["detail"], "a state-changing request with the cookie but WITHOUT the CSRF header: 403")
ok(c.post(cancel, headers=csrf_hdr("wrong-token")).status_code == 403, "wrong CSRF token: 403")
ok(c.post(cancel, headers=csrf_hdr(csrf)).status_code == 404, "right CSRF token: the request goes through (404 = no such job)")
ok(c.post(cancel, headers=csrf_hdr(csrf, {"Origin": EVIL})).status_code == 403, "right token but a foreign Origin: 403")
ok(c.post(cancel, headers={"X-CSRF-Token": csrf}).status_code == 404, "no Origin header at all (not a browser): the token is enough")
other = new_client()
login(other, "bob")
ok(other.post(cancel, headers=csrf_hdr(csrf)).status_code == 403, "another user's CSRF token does not work for me")
ok(c.get("/api/usage", headers=APP_H).status_code == 200, "reading (GET) needs no CSRF token")

# ================= 4. bearer clients are unchanged =================
tok = login(new_client(), "alice", cookie=False).json()["token"]
ok(login(new_client(), "alice", cookie=False).json().get("csrf_token") is None, "cookie=false (API clients): the token is in the body as before")
api = new_client()
ok(api.post(cancel, headers={"Authorization": f"Bearer {tok}"}).status_code == 404, "bearer: no CSRF header needed (no cookie involved)")
bob_tok = login(new_client(), "bob", cookie=False).json()["token"]
r = c.get("/api/auth/me", headers={**APP_H, "Authorization": f"Bearer {bob_tok}"})
ok(r.json()["email"] == "bob@x.com", "if both are sent, the bearer token wins (and needs no CSRF)")

# ================= 5. admin and normal app stay separate =================
r = login(new_client(), "alice", ADM_H, "admin")
ok(r.status_code == 403 and "not an admin" in r.json()["detail"] and "set-cookie" not in r.headers, "a normal account cannot get an admin cookie")
r = login(new_client(), "root", {"Origin": APP, "X-Audience": "admin"}, "admin")
ok(r.status_code == 403 and "set-cookie" not in r.headers, "an admin cookie is not issued to the USER app's origin (admin sign-in only from the dashboard)")
r = login(new_client(), "root", {"X-Audience": "admin"}, "admin")
ok(r.status_code == 403, "... nor without any Origin")
adm = new_client()
r = login(adm, "root", ADM_H, "admin")
ok(r.status_code == 200 and adm.cookies.get("admin_session") and adm.cookies.get("session") is None and r.headers["set-cookie"].startswith("admin_session="),
   "an admin signs in from the dashboard: admin_session cookie only")
age = int(r.headers["set-cookie"].split("Max-Age=")[1].split(";")[0])
ok(age == 3600, f"admin cookies live 60 minutes ({age}s)")
adm_csrf = r.json()["csrf_token"]
ok(adm.get("/api/admin/overview", headers=ADM_H).status_code == 200, "the admin API works with the admin cookie from the dashboard")
r = adm.get("/api/admin/overview", headers={"Origin": APP, "X-Audience": "admin"})
ok(r.status_code == 403 and "dashboard" in r.json()["detail"], "THE SAME admin cookie sent from the user app's origin is refused (a script injected into the user app cannot ride it)")
ok(adm.get("/api/admin/overview", headers={"X-Audience": "admin"}).status_code == 403, "... and without an Origin")
r = adm.get("/api/admin/overview", headers=APP_H)
ok(r.status_code == 401, "from the user app without the admin header the admin cookie is not even looked at")
patch = adm.patch(f"/api/admin/users/{ids['bob']}", headers={**ADM_H, "X-CSRF-Token": adm_csrf}, json={"daily_minutes": 55})
ok(patch.status_code == 200 and patch.json()["daily_minutes"] == 55, "an admin change with the CSRF token works")
ok(adm.patch(f"/api/admin/users/{ids['bob']}", headers=ADM_H, json={"daily_minutes": 1}).status_code == 403, "... and is refused without it")
# an admin who also signed in to the normal app in the same browser
both = new_client()
login(both, "root", ADM_H, "admin")
login(both, "root", APP_H, "app")
ok(both.cookies.get("admin_session") and both.cookies.get("session"), "an admin can hold both cookies in one browser")
r = both.get("/api/admin/overview", headers=APP_H)
ok(r.status_code == 403, "the normal-app session of an admin account does NOT open the admin API")
ok(both.get("/api/auth/me", headers=APP_H).json()["is_admin"] is True, "... but works as a normal session")

# ================= 6. renewing =================
old_cookie = c.cookies.get("session")
r = c.post("/api/auth/refresh", headers=csrf_hdr(csrf))
new_cookie = c.cookies.get("session")
ok(r.status_code == 200 and "token" not in r.json() and r.json()["csrf_token"] != csrf, "refresh: a new CSRF token, no token in the body")
ok("set-cookie" in r.headers and new_cookie != old_cookie, "refresh: a new cookie")
ok(jwt.decode(new_cookie, auth.SECRET, algorithms=["HS256"])["ses"] == jwt.decode(old_cookie, auth.SECRET, algorithms=["HS256"])["ses"], "the session start is kept (renewals cannot run for ever)")
csrf = r.json()["csrf_token"]
ok(c.post("/api/auth/refresh", headers=APP_H).status_code == 403, "refresh needs the CSRF token too")
stale = new_client()
claims = jwt.decode(new_cookie, auth.SECRET, algorithms=["HS256"])
stale.cookies.set("session", jwt.encode({**claims, "ses": int(time.time()) - 61 * 86400}, auth.SECRET, algorithm="HS256"), path="/api")
ok(stale.post("/api/auth/refresh", headers=csrf_hdr(auth.csrf_for(stale.cookies.get("session")))).status_code == 401, "a session older than its maximum cannot be renewed")

# ================= 7. logging out =================
r = c.post("/api/auth/logout", headers=APP_H)
ok(r.status_code == 200 and "session=" in r.headers.get("set-cookie", "") and ("Max-Age=0" in r.headers["set-cookie"] or "1970" in r.headers["set-cookie"]), "logout: the server clears the cookie (JavaScript cannot delete an httpOnly cookie)")
ok(c.get("/api/auth/me", headers=APP_H).status_code == 401, "afterwards the session is gone")
ok(new_client().post("/api/auth/logout", headers=APP_H).status_code == 200, "logging out always works, even with no session")

c2 = new_client()
r = login(c2, "alice")
t_before = login(new_client(), "alice", cookie=False).json()["token"]
ok(c2.post("/api/auth/logout-all", headers=csrf_hdr(r.json()["csrf_token"])).status_code == 200, "log out everywhere")
ok(c2.get("/api/auth/me", headers=APP_H).status_code == 401 and api.get("/api/auth/me", headers={"Authorization": f"Bearer {t_before}"}).status_code == 401,
   "this browser's cookie and every other session are dead")

# ================= 8. revocation reaches cookie sessions =================
victim = new_client()
login(victim, "bob")
rt = login(adm, "root", ADM_H, "admin").json()["csrf_token"]
adm.patch(f"/api/admin/users/{ids['bob']}", headers={**ADM_H, "X-CSRF-Token": rt}, json={"password": "bob-new-password"})
ok(victim.get("/api/auth/me", headers=APP_H).status_code == 401, "an admin password reset ends a cookie session too")

# ================= 9. sign-up =================
fresh = new_client()
ratelimit._memory = ratelimit.MemoryStore()
r = fresh.post("/api/auth/register", headers=APP_H, json={"email": "new@x.com", "password": "password123", "cookie": True})
ok(r.status_code == 200 and "token" not in r.json() and fresh.cookies.get("session") and r.json()["csrf_token"], "sign-up with cookie=true: cookie + CSRF token, no token in the body")
ratelimit._memory = ratelimit.MemoryStore()
r = new_client().post("/api/auth/register", headers={"Origin": EVIL}, json={"email": "evil@x.com", "password": "password123", "cookie": True})
with Session() as s:
    made = s.query(User).filter(User.email == "evil@x.com").count()
ok(r.status_code == 403 and made == 0, "a foreign origin cannot sign anyone up")
r = login(new_client(), "alice", {"Origin": EVIL})
ok(r.status_code == 403 and "set-cookie" not in r.headers, "a foreign origin cannot get a login cookie")

# ================= 10. uploads: the guard understands cookies =================
up = new_client()
login(up, "alice")
up_csrf = up.get("/api/auth/me", headers=APP_H).json()["csrf_token"]
files = {"video_file": ("a.mp4", b"x" * 500, "video/mp4")}
ok(new_client().post("/api/jobs", headers=APP_H, files=files, data={"output": "subtitles"}).status_code == 401, "upload without a session: 401 before the body is read")
r = up.post("/api/jobs", headers=APP_H, files=files, data={"output": "subtitles"})
ok(r.status_code == 403 and "Security check" in r.json()["detail"], "upload with the cookie but no CSRF token: 403 (also before the body is read)")
r = up.post("/api/jobs", headers=csrf_hdr(up_csrf), files=files, data={"output": "subtitles"})
ok(r.status_code == 200 and r.json().get("job_id"), "upload with cookie + CSRF token works")
r = up.post("/api/jobs", headers=csrf_hdr(up_csrf, {"Origin": EVIL}), files=files, data={"output": "subtitles"})
ok(r.status_code == 403, "upload from a foreign origin: 403")

# ================= 11. CORS with credentials =================
pre = new_client().options("/api/auth/me", headers={"Origin": APP, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-csrf-token,x-audience"})
ok(pre.headers.get("access-control-allow-origin") == APP and pre.headers.get("access-control-allow-credentials") == "true", "preflight from the app: its origin is echoed, credentials allowed")
ok("x-csrf-token" in pre.headers.get("access-control-allow-headers", "").lower(), "... and the CSRF header is allowed")
pre = new_client().options("/api/auth/me", headers={"Origin": EVIL, "Access-Control-Request-Method": "GET"})
ok("access-control-allow-origin" not in pre.headers, "preflight from a foreign site: no CORS permission")
r = up.get("/api/auth/me", headers=APP_H)
ok(r.headers.get("access-control-allow-credentials") == "true" and r.headers.get("access-control-allow-origin") == APP, "real answers carry the credentials header")
r = up.get("/api/auth/me", headers={"Origin": EVIL})
ok("access-control-allow-origin" not in r.headers, "a foreign site gets no CORS header, so it cannot read the answer (nor the CSRF token)")
ok(main.app.user_middleware and any("*" not in str(m.kwargs.get("allow_origins")) for m in main.app.user_middleware if m.cls.__name__ == "CORSMiddleware"), "CORS origins are explicit (never * together with cookies)")

print("ALL OK")
