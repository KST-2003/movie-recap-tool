"""Offline test: users never see raw error text (paths, vendor error bodies, project ids, keys); admins still do (security fix).
Before: a failed job showed "Recap generation failed: <ffmpeg stderr / Google error body>" and a failed preview showed the first 160 characters
of the exception; both go to a browser anywhere.
Run: python test_error_messages.py"""
import os
import re
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")
os.environ.pop("REDIS_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import common  # noqa: E402
import gemini_tts  # noqa: E402
import main  # noqa: E402
import pipeline  # noqa: E402
import tts_pool  # noqa: E402
from db import Job, Session, User  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


LEAKS = ["/home/ubuntu", "C:\\Users", "does_not_exist", "AIzaSyFAKEKEY123", "recaptool-514214", "RESOURCE_EXHAUSTED", "Traceback", "ffmpeg version",
         "secret-token-xyz", "Gemini", "Upgrade"]


def leaks(text):
    return [w for w in LEAKS if w in text]


client = TestClient(main.app, raise_server_exceptions=False)
users = {}
with Session() as s:
    for name, admin in (("alice", False), ("root", True)):
        u = User(email=f"{name}@x.com", password_hash=auth.hash_password("pw-pw-pw-pw"), daily_minutes=100, monthly_minutes=1000, is_admin=admin)
        s.add(u)
        s.commit()
        users[name] = (u.id, {"Authorization": "Bearer " + auth.make_token(u)})
alice_id, alice = users["alice"]
_, root = users["root"]
messages = []   # every text a user can receive in this test (checked against the Burmese rules at the end)


def job(jid, **kw):
    with Session() as s:
        s.add(Job(id=jid, user_id=alice_id, status=kw.pop("status", "running"), params=kw.pop("params", {"mode": "recap", "output": "subtitles"}), data={}, **kw))
        s.commit()


def view(jid):
    r = client.get(f"/api/jobs/{jid}", headers=alice)
    assert r.status_code == 200, r.text
    return r.json()


# ---- 1. a failing job: the user gets a code, the admin gets the reason ----
RAW = ("Gemini TTS failed: 429 RESOURCE_EXHAUSTED. project recaptool-514214 key=AIzaSyFAKEKEY123 "
       "file /home/ubuntu/app/does_not_exist.mp4 ffmpeg version 7.1 secret-token-xyz")
job("job000000001")
pipeline.fail_job("job000000001", RuntimeError(RAW))
v = view("job000000001")
messages.append(v["error"])
ok(v["status"] == "error" and "job000000001" in v["error"] and not leaks(json_text := str(v)), f"user sees only the generic text + code: {v['error'][:90]}...")
ok("error_detail" not in v and "usage" not in v, "the job view hides error_detail and token usage")
r = client.get("/api/admin/jobs", headers=root).json()["items"]
mine = next(i for i in r if i["id"] == "job000000001")
ok("secret-token-xyz" in mine["error_detail"] and "RuntimeError" in mine["error_detail"], "the admin jobs list still shows the real error")
ok(not leaks(mine["error"]), "... next to the safe text")

# ---- 2. messages written for users pass through unchanged ----
for n, exc in enumerate((pipeline.JobTooSlow("This video took longer than 12 minutes (the services were slow or busy). Please try again; nothing was charged."),
                         common.UserError("The edited project has no lines."),
                         gemini_tts.QuotaExceeded(gemini_tts.quota_message()))):
    jid = f"job00000010{n}"
    job(jid)
    pipeline.fail_job(jid, exc)
    ok(view(jid)["error"] == str(exc), f"written-for-users error passes through: {str(exc)[:60]}")
    messages.append(str(exc))
ok(not leaks(gemini_tts.quota_message()) and not leaks(tts_pool.blocked_message()), "quota texts name no vendor and do not tell users to 'upgrade'")
messages += [gemini_tts.quota_message(), tts_pool.blocked_message()]

# ---- 3. the REAL pipeline failing: a job whose source file is gone ----
missing = os.path.join(tmp, "uploads", "does_not_exist.mp4")
job("job000000002", status="queued", input_key=missing)
pipeline.run_job_by_id("job000000002")
v = view("job000000002")
messages.append(v["error"])
with Session() as s:
    detail = s.get(Job, "job000000002").data.get("error_detail", "")
ok(v["status"] == "error" and "job000000002" in v["error"] and not leaks(str(v)), f"real failed run: user sees the generic text only ({v['error'][:50]}...)")
ok("does_not_exist" in detail, "... and the real reason (with the path) was kept for the admin")

# ---- 4. preview failures ----
proj = {"voice": "Kore", "source_duration": 60.0, "fx": {}, "segments": [{"id": 1, "start": 1.0, "text": "hello"}]}
with Session() as s:
    s.add(Job(id="job000000003", user_id=alice_id, status="done", params={"output": "subtitles"}, input_key=missing,
              data={"result": {"project": proj}}))
    s.commit()


def preview(text):
    return client.post("/api/jobs/job000000003/preview-line", headers=alice, json={"id": 1, "text": text, "voice": "Kore"})


real = pipeline.voice_many


def boom(*a, **k):
    raise RuntimeError(RAW)


pipeline.voice_many = boom
r = preview("first line")
ok(r.status_code == 502 and not leaks(r.text), f"preview failure: 502 with a plain message ({r.json()['detail']})")
messages.append(r.json()["detail"])


def blocked(*a, **k):
    raise pipeline.LineBlocked(RAW)


pipeline.voice_many = blocked
r = preview("second line")
ok(r.status_code == 422 and not leaks(r.text), f"refused line: 422 with advice ({r.json()['detail']})")
messages.append(r.json()["detail"])
pipeline.voice_many = real

# ---- 5. anything unexpected: a code and nothing else ----
@main.app.get("/api/_boom")
def _boom():
    raise ValueError("secret-token-xyz at /home/ubuntu/app/does_not_exist.py AIzaSyFAKEKEY123")


r = client.get("/api/_boom")
body = r.json()
ok(r.status_code == 500 and not leaks(r.text) and re.search(r"code: [0-9a-f]{8}", body["detail"]), f"unexpected error: 500 + code only ({body['detail']})")
messages.append(body["detail"])

# ---- 6. the other texts this branch added are safe, and every user-facing text has a Burmese rule ----
messages += [c for c in ("Too many attempts. Try again in 15 minutes.", "Password can be at most 256 characters.",
                         "You have used all 10 voice previews for this video. Try again with a new video.",
                         "Daily limit reached (30 voice previews a day). Try again tomorrow.",
                         "That file type is not supported. Use MP4, MOV, MKV, WebM, AVI, FLV or TS.", "That file has no video track.",
                         "Video size must be at most 8192 pixels per side.", "The logo must be a PNG, JPEG, WebP, GIF or BMP image.",
                         "Session expired. Please log in again.",
                         "Monthly limit reached: 1.0 of your 10 minutes left this month, this video is 10.0 minutes.")]
src = open(os.path.join("..", "frontend", "src", "i18n.jsx"), encoding="utf-8").read()
block = src[src.index("const SERVER = ["):src.index("export function makeTr")]
rules = [re.compile(m) for m in re.findall(r"^\s*\[/(.+?)/,\s", block, re.M)]   # a rule's Burmese text may start on the next line
ok(len(rules) > 30, f"read {len(rules)} Burmese rules from i18n.jsx")
missing_rules = [m[:80] for m in messages if not any(r.search(m) for r in rules)]
ok(not missing_rules, f"all {len(messages)} user-facing texts have a Burmese rule" + ("" if not missing_rules else f": missing {missing_rules}"))

print("ALL OK")
