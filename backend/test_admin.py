"""Offline test of the admin API (/api/admin/*): access control, overview, users, jobs, TTS pool, runtime settings.
Run: python test_admin.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")   # offline: never Google Cloud, whatever backend/.env says

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
from db import Job, Session, User, update_job  # noqa: E402
from admin import google_quota  # noqa: E402
from main import app  # noqa: E402

google_quota._list_models = lambda: {}   # never call Google from this offline test

c = TestClient(app)
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)

with Session() as s:
    admin = User(email="boss@x.com", password_hash=auth.hash_password("password1"), is_admin=True, daily_minutes=60)
    user = User(email="bob@x.com", password_hash=auth.hash_password("password2"), daily_minutes=20)
    s.add_all([admin, user]); s.commit()
    for i, st in enumerate(["done", "error", "running", "queued"]):
        s.add(Job(id=f"job{i}", user_id=user.id, status=st, params={"mode": "recap", "output": "dub"}, data={"run_seconds": 100 + i},
                  charged_seconds=0.0 if st == "error" else 300.0))
    s.commit()
    admin_id, user_id = admin.id, user.id

login = lambda e, p: c.post("/api/auth/login", json={"email": e, "password": p}).json()  # noqa: E731
a, b = login("boss@x.com", "password1"), login("bob@x.com", "password2")
H = lambda t: {"Authorization": f"Bearer {t['token']}"}  # noqa: E731
ok(a["is_admin"] is True and b["is_admin"] is False, "login reports is_admin")
ok(c.get("/api/auth/me", headers=H(a)).json()["is_admin"] is True, "/me reports is_admin")

# access control
ok(c.get("/api/admin/overview").status_code == 401, "no token -> 401")
ok(c.get("/api/admin/overview", headers=H(b)).status_code == 403, "normal user -> 403")
ok(c.get("/api/admin/users", headers=H(b)).status_code == 403, "normal user cannot list users")

# overview
o = c.get("/api/admin/overview", headers=H(a)).json()
ok(o["users"]["total"] == 2 and o["jobs_today"]["total"] == 4 and o["jobs_today"]["error"] == 1, "overview counts")
ok(o["queue"]["queued"] == 1 and o["queue"]["running"] == 1, "overview queue")
ok(o["minutes_today"] == 15.0 and len(o["series"]) == 14 and o["series"][-1]["jobs"] == 4, "overview minutes + series")

# users
u = c.get("/api/admin/users?q=bob", headers=H(a)).json()
ok(u["total"] == 1 and u["items"][0]["used_minutes_today"] == 15.0, "user search + usage")
ok(c.post("/api/admin/users", headers=H(a), json={"email": "new@x.com", "password": "password3", "daily_minutes": 5}).status_code == 200, "create user")
ok(c.post("/api/admin/users", headers=H(a), json={"email": "new@x.com", "password": "password3"}).status_code == 409, "duplicate email")
ok(c.post("/api/admin/users", headers=H(a), json={"email": "bad name!", "password": "password3"}).status_code == 400, "bad username")
r = c.patch(f"/api/admin/users/{user_id}", headers=H(a), json={"daily_minutes": 99, "password": "newpassword"}).json()
ok(r["daily_minutes"] == 99 and login("bob@x.com", "newpassword").get("token"), "set minutes + reset password")
c.patch(f"/api/admin/users/{user_id}", headers=H(a), json={"is_active": False})
ok(c.post("/api/auth/login", json={"email": "bob@x.com", "password": "newpassword"}).status_code == 403, "disabled user cannot log in (told why)")
ok(c.patch(f"/api/admin/users/{admin_id}", headers=H(a), json={"is_admin": False}).status_code == 400, "cannot demote yourself")
ok(c.patch(f"/api/admin/users/{admin_id}", headers=H(a), json={"is_active": False}).status_code == 400, "cannot disable yourself")
ok(c.patch("/api/admin/users/9999", headers=H(a), json={"daily_minutes": 1}).status_code == 404, "unknown user")

# jobs
j = c.get("/api/admin/jobs?status=error", headers=H(a)).json()
ok(j["total"] == 1 and j["items"][0]["email"] == "bob@x.com", "jobs filter by status")
ok(c.get("/api/admin/jobs?status=nope", headers=H(a)).status_code == 400, "bad status filter")
ok(c.get(f"/api/admin/jobs?user_id={user_id}&per_page=2", headers=H(a)).json()["items"].__len__() == 2, "jobs paging")
ok(c.post("/api/admin/jobs/job2/cancel", headers=H(a)).json()["status"] == "cancelled", "cancel running job")
ok(c.post("/api/admin/jobs/job0/cancel", headers=H(a)).status_code == 409, "cannot cancel finished job")

# tts pool
t = c.get("/api/admin/tts", headers=H(a)).json()
ok(len(t["models"]) == 5 and t["models"][0]["remaining"] == 100 and t["all_blocked"] is False, "tts pool status")
ok(t["cloud"]["configured"] is False and t["models"][0]["cloud"] is None and t["models"][0]["google"] == {"exists": False}, "tts: no cloud configured, model not in key list")

# runtime settings
ok(c.get("/api/admin/settings", headers=H(a)).json()["maintenance"] is False, "maintenance off by default")
c.put("/api/admin/settings", headers=H(a), json={"maintenance": True, "global_daily_minutes": 500})
s_ = c.get("/api/admin/settings", headers=H(a)).json()
ok(s_["maintenance"] is True and s_["global_daily_minutes"] == 500, "settings saved")
blocked = c.post("/api/jobs", headers=H(login("boss@x.com", "password1")), files={"video_file": ("a.mp4", b"x")})
ok(blocked.status_code == 503, "maintenance blocks new jobs without restart")
c.put("/api/admin/settings", headers=H(a), json={"maintenance": False})
ok(c.get("/api/admin/overview", headers=H(a)).json()["maintenance"] is False, "maintenance off again")
# audit log: one row per successful change, none for refused ones, never a password
au = c.get("/api/admin/audit", headers=H(a)).json()
by = {}
for r in au["items"]:
    by[r["action"]] = by.get(r["action"], 0) + 1
ok(au["total"] == 6 and by == {"user.create": 1, "user.update": 2, "job.cancel": 1, "settings.update": 2}, f"audit rows only for successful changes {by}")
ok(all(r["admin_email"] == "boss@x.com" for r in au["items"]), "audit records who did it")
upd = [r for r in au["items"] if r["action"] == "user.update" and "daily_minutes" in r["details"]][0]
ok(upd["target_label"] == "bob@x.com" and upd["details"]["daily_minutes"] == {"from": 20, "to": 99} and upd["details"]["password_reset"] is True, "audit shows old -> new and a password reset")
ok("newpassword" not in str(au), "audit never contains the password")
st = [r for r in au["items"] if r["action"] == "settings.update"][-1]
ok(st["details"]["maintenance"] == {"from": False, "to": True}, "audit shows settings change")
ok(c.get("/api/admin/audit?action=job.cancel", headers=H(a)).json()["total"] == 1, "audit filter by action")
ok(c.get("/api/admin/audit?action=nope", headers=H(a)).status_code == 400, "audit bad action")
ok(c.get("/api/admin/audit", headers=H(b)).status_code in (401, 403), "audit is closed to non-admins (bob was disabled above, so 401)")
ok(c.get("/api/admin/audit").status_code == 401, "audit needs a token")
c.put("/api/admin/settings", headers=H(a), json={"maintenance": False})
ok(c.get("/api/admin/audit", headers=H(a)).json()["total"] == 6, "no-op settings save is not logged")

# job detail: full error, where it failed, every option the user chose
with Session() as s:
    s.add(Job(id="jobx", user_id=user_id, status="queued", params={"mode": "full", "voice_quality": "standard", "voice_type": "Kore", "aspect": "9:16", "manual_blurs": [{"x": 0.1}], "filename": "movie.mp4"},
              data={}, charged_seconds=120.0, credit_seconds=60.0))
    s.commit()
update_job("jobx", status="running", stage="Starting", progress=1)
update_job("jobx", stage="Voiceover (gemini)", progress=40)
update_job("jobx", status="error", error="Recap generation failed: ffmpeg: Unrecognized option", error_detail="Traceback (most recent call last):\n  File x\nRuntimeError: boom")
d = c.get("/api/admin/jobs/jobx", headers=H(a)).json()
ok(d["status"] == "error" and d["error"].endswith("Unrecognized option") and "RuntimeError: boom" in d["error_detail"], "detail: full error + technical details")
ok(d["failed_stage"]["stage"] == "Voiceover (gemini)" and d["failed_stage"]["progress"] == 40, "detail: knows which stage failed")
ok([x["stage"] for x in d["stages"]] == ["Starting", "Voiceover (gemini)"], f"detail: stage history {[x['stage'] for x in d['stages']]}")
ok(d["params"]["voice_quality"] == "standard" and d["params"]["aspect"] == "9:16" and d["params"]["manual_blurs"] == [{"x": 0.1}] and d["params"]["filename"] == "movie.mp4", "detail: every option the user chose")
ok(d["user"]["email"] == "bob@x.com" and d["bought_minutes"] == 0.0, "detail: user shown; a failed video's bought minutes were given back")
import joblog, usage  # noqa: E402
joblog.install()
usage.start("jobx")
print("  fake pipeline line: scene cuts found 69", flush=True)
usage.start(None)
import db as _db  # noqa: E402
_db.save_log("jobx")
d2 = c.get("/api/admin/jobs/jobx", headers=H(a)).json()
ok(any("scene cuts found 69" in ln for ln in d2["log"]), f"detail: the video's console log is kept ({len(d2['log'])} lines)")
ok(c.get("/api/admin/jobs/nope", headers=H(a)).status_code == 404, "detail: unknown job -> 404")
ok(c.get("/api/admin/jobs/jobx", headers=H(b)).status_code in (401, 403) and c.get("/api/admin/jobs/jobx").status_code == 401, "detail is closed to non-admins")
print("all admin tests passed")
