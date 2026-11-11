"""Offline test: admin-made logins, device limit, statuses (pause / deactivate / ban), regenerated passwords, device list,
video history and keeping time. Run: python test_accounts.py"""
import os
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", TRUST_PROXY="1")

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import storage  # noqa: E402
from db import Job, Session, User  # noqa: E402
from main import app  # noqa: E402

c = TestClient(app)
for d in ("up", "out", "data"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
SAFARI_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
CHROME_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1"
EDGE = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 Edg/130.0"
ok(auth.parse_ua(CHROME_WIN) == ("Chrome", "Windows") and auth.parse_ua(SAFARI_IPHONE) == ("Safari", "iPhone")
   and auth.parse_ua(CHROME_IOS) == ("Chrome", "iPhone") and auth.parse_ua(EDGE) == ("Edge", "Windows"), "browser + system from the User-Agent")

with Session() as s:
    s.add(User(email="boss", password_hash=auth.hash_password("bosspass1"), is_admin=True, is_superadmin=True)); s.commit()
    boss_id = s.query(User).filter_by(email="boss").one().id
adm = c.post("/api/auth/login", json={"email": "boss", "password": "bosspass1"}).json()
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
A = H(adm["token"])


def login(name, pw, device, ua=CHROME_WIN, ip="1.2.3.4"):
    auth._hits.clear()   # the brute-force guard (10 tries / 10 min per IP) is not what this test is about
    return c.post("/api/auth/login", json={"email": name, "password": pw, "device_id": device}, headers={"user-agent": ua, "x-forwarded-for": ip})


# ---- admin creates logins: generated username + password, device policy chosen ----
r = c.post("/api/admin/users", headers=A, json={"device_limit": 1}).json()
ok(r["email"].startswith("user") and len(r["password"]) == 14 and r["password"].count("-") == 2 and r["device_limit"] == 1, f"generated login {r['email']} / password shown once")
uid, uname, upw = r["id"], r["email"], r["password"]
with Session() as s:
    ok(upw not in s.get(User, uid).password_hash, "only a hash is stored")
ok(c.post("/api/admin/users", headers=A, json={"username": uname, "password": "whatever1"}).status_code == 409, "duplicate username refused")
ok(c.post("/api/admin/users", headers=A, json={"username": "no spaces!"}).status_code == 400, "bad username refused")
two = c.post("/api/admin/users", headers=A, json={"username": "anyone", "device_limit": 0}).json()
ok(two["device_limit"] == 0, "any-device login")

# ---- one device only ----
d1 = login(uname, upw, "device-aaaaaaaa", CHROME_WIN, "10.0.0.1")
ok(d1.status_code == 200 and d1.json()["device_id"] == "device-aaaaaaaa", "first device logs in")
t1 = d1.json()["token"]
ok(login(uname, upw, "device-aaaaaaaa").status_code == 200, "the SAME device can log in again")
bad = login(uname, upw, "device-bbbbbbbb", SAFARI_IPHONE, "10.0.0.2")
ok(bad.status_code == 403 and bad.json()["detail"] == auth.DEVICE_FULL, "a second device is refused")
ok(login(uname, "wrongpass", "device-bbbbbbbb").status_code == 401, "wrong password is 401 (not 403)")
ok(c.get("/api/auth/me", headers={**H(t1), "x-forwarded-for": "10.0.0.1"}).status_code == 200, "the first device keeps working")

# ---- admin sees device, browser, IP ----
row = next(u for u in c.get("/api/admin/users", headers=A).json()["items"] if u["id"] == uid)
ok(row["device_count"] == 1 and row["last_browser"] == "Chrome" and row["last_os"] == "Windows" and row["last_ip"] == "10.0.0.1"
   and row["last_device"] == "Chrome on Windows" and row["status"] == "active", f"admin table: {row['last_device']} {row['last_ip']}")
devs = c.get(f"/api/admin/users/{uid}/devices", headers=A).json()["items"]
ok(len(devs) == 1, "device list")
c.get("/api/auth/me", headers={**H(t1), "x-forwarded-for": "10.9.9.9"})
ok(c.get(f"/api/admin/users/{uid}/devices", headers=A).json()["items"][0]["ip"] == "10.9.9.9", "last IP updates")

# ---- admin removes the device: old one signed out, new one can come ----
ok(c.delete(f"/api/admin/users/{uid}/devices/{devs[0]['id']}", headers=A).status_code == 200, "device removed")
me = c.get("/api/auth/me", headers=H(t1))
ok(me.status_code == 401 and me.json()["detail"] == auth.DEVICE_REMOVED, "the removed device is signed out with a clear message")
ok(login(uname, upw, "device-bbbbbbbb", SAFARI_IPHONE, "10.0.0.2").status_code == 200, "the slot is free for another device")
ok(c.delete(f"/api/admin/users/{uid}/devices", headers=A).json()["removed"] == 1, "remove all devices")

# ---- any number of devices ----
for i in range(4):
    ok(login("anyone", two["password"], f"device-any-{i}x").status_code == 200, f"any-device login: device {i + 1}")

# ---- statuses ----
t = login(uname, upw, "device-cccccccc").json()["token"]
for status in ("paused", "deactivated", "banned"):
    ok(c.patch(f"/api/admin/users/{uid}", headers=A, json={"status": status, "status_reason": "test"}).json()["status"] == status, f"set {status}")
    me = c.get("/api/auth/me", headers=H(t))
    ok(me.status_code == 401 and status in me.json()["detail"], f"{status}: an open session stops at once ({me.json()['detail']})")
    lg = login(uname, upw, "device-cccccccc")
    ok(lg.status_code == 403 and status in lg.json()["detail"], f"{status}: login refused with the reason")
    ok(login(uname, "wrongwrong", "device-cccccccc").json()["detail"] == "Wrong username or password.", f"{status}: a wrong password does not reveal the status")
ok(c.patch(f"/api/admin/users/{uid}", headers=A, json={"status": "active"}).json()["status"] == "active", "resume")
ok(login(uname, upw, "device-cccccccc").status_code == 200, "active again: can log in")
ok(c.patch(f"/api/admin/users/{boss_id}", headers=A, json={"status": "banned"}).status_code == 400, "an admin cannot ban themselves")
ok(c.get("/api/admin/users?status=banned", headers=A).json()["total"] == 0, "status filter")
with Session() as s:
    s.add(Job(id="runjob", user_id=uid, status="running", params={}, data={}, charged_seconds=60.0)); s.commit()
c.patch(f"/api/admin/users/{uid}", headers=A, json={"status": "banned"})
with Session() as s:
    ok(s.get(Job, "runjob").status == "cancelled", "a ban cancels the user's running video")
c.patch(f"/api/admin/users/{uid}", headers=A, json={"status": "active"})

# ---- regenerated password ----
old_token = login(uname, upw, "device-cccccccc").json()["token"]
new = c.post(f"/api/admin/users/{uid}/reset-password", headers=A).json()
ok(new["username"] == uname and new["password"] != upw and len(new["password"]) == 14, "new password generated")
ok(c.get("/api/auth/me", headers=H(old_token)).status_code == 401, "the old session ends when the password changes")
ok(login(uname, upw, "device-cccccccc").status_code == 401, "the old password no longer works")
ok(login(uname, new["password"], "device-cccccccc").status_code == 200, "the new password works (same device)")
ok(c.post("/api/auth/register", json={"email": "x@y.com", "password": "password1"}).status_code == 403, "self sign-up is closed by default")
logs = c.get("/api/admin/audit?per_page=100", headers=A).json()["items"]
ok(any(l["action"] == "user.device" for l in logs) and not any(new["password"] in str(l) for l in logs), "device removals are logged, passwords never")

# ---- video history + keeping time ----
tok = login(uname, new["password"], "device-cccccccc").json()["token"]
res, src = f"{tmp}/out/r1.mp4", f"{tmp}/up/s1.mp4"
open(res, "wb").write(b"x" * 100); open(f"{tmp}/out/r1.srt", "w").write("1"); open(src, "wb").write(b"y" * 50)
with Session() as s:
    s.add(Job(id="h1", user_id=uid, status="done", params={"mode": "recap", "output": "dub", "filename": "movie.mp4"}, input_key=src,
              data={"result": {"video_file": "r1.mp4", "subtitle_file": "r1.srt", "project": {"source_duration": 90.0, "segments": []}}}, charged_seconds=90.0))
    s.add(Job(id="h2", user_id=uid, status="error", params={}, data={}, error="boom", charged_seconds=0.0))
    s.commit()
h = c.get("/api/jobs", headers=H(tok)).json()
row = next(r for r in h["items"] if r["id"] == "h1")
ok(h["total"] == 2 and row["title"] == "movie.mp4" and row["minutes"] == 1.5 and row["video_available"] and row["can_edit"] and row["expires_at"], "history lists my videos with expiry")
ok(h["keep_result_days"] == 30 and h["keep_source_days"] == 7, "default keeping time 30 / 7 days")
other = login("anyone", two["password"], "device-any-0x").json()["token"]
ok(c.get("/api/jobs", headers=H(other)).json()["total"] == 0, "nobody sees another user's history")
old = time.time() - 10 * 86400
os.utime(src, (old, old))
storage.cleanup()
ok(not os.path.exists(src) and os.path.exists(res) and os.path.exists(f"{tmp}/out/r1.srt"), "after 10 days: source removed, video + subtitles kept")
row = next(r for r in c.get("/api/jobs", headers=H(tok)).json()["items"] if r["id"] == "h1")
ok(row["video_available"] and not row["can_edit"], "history: video still playable, editing no longer possible")
older = time.time() - 40 * 86400
os.utime(res, (older, older)); storage.cleanup()
row = next(r for r in c.get("/api/jobs", headers=H(tok)).json()["items"] if r["id"] == "h1")
ok(not os.path.exists(res) and not row["video_available"] and row["expires_at"] is None, "after 40 days: video removed, the row stays as expired")
ok(c.get("/api/jobs/h1", headers=H(tok)).json()["result"]["expired"] is True, "job view says expired")
c.put("/api/admin/settings", headers=A, json={"keep_result_days": 60, "keep_source_days": 14})
ok(c.get("/api/jobs", headers=H(tok)).json()["keep_result_days"] == 60, "the admin can change the keeping time")
ok(c.put("/api/admin/settings", headers=A, json={"keep_result_days": 0}).status_code == 422, "0 days refused")
st = c.get("/api/admin/settings", headers=A).json()
ok(st["keep_result_days"] == 60 and st["storage"]["total"] >= 0, "settings show days + disk use")
open(res, "wb").write(b"x"); open(src, "wb").write(b"y")
ok(c.delete("/api/jobs/h1", headers=H(tok)).status_code == 200 and not os.path.exists(res) and not os.path.exists(src), "delete removes the files")
ok(all(r["id"] != "h1" for r in c.get("/api/jobs", headers=H(tok)).json()["items"]), "deleted video leaves the list")
ok(c.delete("/api/jobs/h1", headers=H(other)).status_code == 404, "cannot delete another user's video")
with Session() as s:
    s.add(Job(id="h3", user_id=uid, status="running", params={}, data={})); s.commit()
ok(c.delete("/api/jobs/h3", headers=H(tok)).status_code == 409, "a running video cannot be deleted")
print("ALL OK")
