"""Offline test: trial accounts (any number of devices, no videos / edits / previews / link fetches / top-ups, is_trial in me+login).
Run: python test_trial.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)
from fastapi.testclient import TestClient  # noqa: E402
import auth, main  # noqa: E402
from db import Session, User, UserDevice  # noqa: E402

def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)

with Session() as s:
    s.add(User(email="boss", password_hash="x", is_admin=True, is_superadmin=True)); s.commit()
    B = {"Authorization": f"Bearer {auth.make_token(s.query(User).filter_by(email='boss').one())}"}
c = TestClient(main.app)
r = c.post("/api/admin/users", headers=B, json={"username": "tri", "password": "password123", "trial": True, "device_limit": 1, "months": 1})
ok(r.status_code == 200 and r.json()["is_trial"] and r.json()["device_limit"] == 0, "trial account created with unlimited devices")
for i in range(4):
    lr = c.post("/api/auth/login", json={"email": "tri", "password": "password123", "device_id": f"device-000{i}"})
    ok(lr.status_code == 200 and lr.json()["is_trial"], f"login on device {i}")
with Session() as s:
    ok(s.query(UserDevice).count() == 4, "all 4 devices kept (nobody signed out)")
H = {"Authorization": f"Bearer {lr.json()['token']}"}
ok(c.get("/api/auth/me", headers=H).json()["is_trial"] is True, "me says trial")
ok(c.get("/api/auth/me", headers=B).json()["is_trial"] is False, "admin is not trial")
r = c.post("/api/jobs", headers=H, files={"video_file": ("a.mp4", b"x", "video/mp4")})
ok(r.status_code == 402 and "trial" in r.json()["detail"].lower(), "creating a video is refused (402)")
ok(c.post("/api/link/fetch", headers=H, json={"url": "https://xhslink.com/x"}).status_code == 402, "link fetch refused")
ok(c.post("/api/jobs/abc/rerender", headers=H, json={"segments": [{"id": 0, "start": 0, "text": "x"}]}).status_code == 402, "re-render refused")
ok(c.post("/api/jobs/abc/preview-line", headers=H, json={"voice": "Kore", "text": "hi"}).status_code in (402,), "line preview refused")
ok(c.post("/api/topup/requests", headers=H, data={"minutes": 30}, files={"slip": ("s.png", b"x", "image/png")}).status_code == 402, "top-up refused")
# upgrade to a full account: limit back to normal rules
uid = c.get("/api/admin/users?q=tri", headers=B).json()["items"][0]["id"]
r = c.patch(f"/api/admin/users/{uid}", headers=B, json={"is_trial": False, "device_limit": 1, "daily_minutes": 30, "monthly_minutes": 300})
ok(r.status_code == 200 and not r.json()["is_trial"], "admin upgrades the trial account")
r = c.post("/api/jobs", headers=H, files={"video_file": ("a.mp4", b"x", "video/mp4")})
ok(r.status_code != 402 or "trial" not in r.json().get("detail", "").lower(), "after the upgrade the trial refusal is gone")
r = c.patch(f"/api/admin/users/{uid}", headers=B, json={"is_trial": True})
ok(r.json()["is_trial"] and r.json()["device_limit"] == 0, "back to trial sets unlimited devices")
print("ALL OK")
