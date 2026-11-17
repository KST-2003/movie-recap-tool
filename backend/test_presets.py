"""Offline test: presets (users' own, max 5; admin-made, draft / published) and the re-render price (3 free, then 40% of the minutes).
Run: python test_presets.py"""
import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ALLOW_SIGNUP="true")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import jobs_queue  # noqa: E402
import main  # noqa: E402
from db import AuditLog, Job, Session, User  # noqa: E402

jobs_queue.enqueue = lambda job_id: None   # nothing should really run


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    s.add_all([User(email="boss", password_hash="x", is_admin=True, is_superadmin=True), User(email="amy", password_hash="x", daily_minutes=100, monthly_minutes=2000),
               User(email="bob", password_hash="x")])
    s.commit()
    H = {u.email: {"Authorization": f"Bearer {auth.make_token(u)}"} for u in s.query(User).all()}
c = TestClient(main.app)

# ---- presets ----
good = {"aspect": "9:16", "fitMode": "crop", "brightness": 0.1, "flip": True, "voiceQuality": "standard", "outputKind": "dub", "evil": 1,
        "captionStyle": {"font": "serif", "color": "#ffffff", "size": 1.2, "junk": 5}}
r = c.post("/api/presets", json={"name": "Reels", "settings": good}, headers=H["amy"])
ok(r.status_code == 200 and r.json()["settings"]["aspect"] == "9:16", "a user can save a preset")
ok("evil" not in r.json()["settings"] and "junk" not in r.json()["settings"]["captionStyle"], "unknown keys are dropped")
ok(c.post("/api/presets", json={"name": "x", "settings": {"aspect": "7:3"}}, headers=H["amy"]).status_code == 400, "bad value refused")
ok(c.post("/api/presets", json={"name": "x", "settings": {"brightness": 9}}, headers=H["amy"]).status_code == 400, "out of range refused")
ok(c.post("/api/presets", json={"name": " ", "settings": {}}, headers=H["amy"]).status_code == 400, "name needed")
for i in range(4):
    ok(c.post("/api/presets", json={"name": f"P{i}", "settings": {"aspect": "1:1"}}, headers=H["amy"]).status_code == 200, f"preset {i + 2} of 5")
r = c.post("/api/presets", json={"name": "sixth", "settings": {}}, headers=H["amy"])
ok(r.status_code == 400 and "5" in r.json()["detail"], "the 6th is refused")
mine = c.get("/api/presets", headers=H["amy"]).json()
ok(len(mine["mine"]) == 5 and mine["max"] == 5, "list shows 5 / max 5")
ok(c.get("/api/presets", headers=H["bob"]).json()["mine"] == [], "another user sees none of them")
pid = mine["mine"][0]["id"]
ok(c.put(f"/api/presets/{pid}", json={"name": "Reels 2", "settings": {"aspect": "16:9"}}, headers=H["bob"]).status_code == 404, "cannot edit someone else's")
ok(c.put(f"/api/presets/{pid}", json={"name": "Reels 2", "settings": {"aspect": "16:9"}}, headers=H["amy"]).json()["name"] == "Reels 2", "edit own")
ok(c.delete(f"/api/presets/{pid}", headers=H["bob"]).status_code == 404, "cannot delete someone else's")
ok(c.delete(f"/api/presets/{pid}", headers=H["amy"]).status_code == 200, "delete own")
ok(c.post("/api/presets", json={"name": "again", "settings": {}}, headers=H["amy"]).status_code == 200, "room again after delete")

# admin presets
ok(c.get("/api/admin/presets", headers=H["amy"]).status_code == 403, "users cannot use the admin API")
r = c.post("/api/admin/presets", json={"name": "Recat TikTok", "settings": {"aspect": "9:16"}}, headers=H["boss"])
ok(r.status_code == 200 and r.json()["status"] == "draft", "admin preset starts as a draft")
aid = r.json()["id"]
ok(c.get("/api/presets", headers=H["bob"]).json()["shared"] == [], "a draft is invisible to users")
ok(c.put(f"/api/admin/presets/{aid}", json={"name": "Recat TikTok", "settings": {"aspect": "9:16"}, "status": "published"}, headers=H["boss"]).json()["status"] == "published", "submit (publish)")
sh = c.get("/api/presets", headers=H["bob"]).json()["shared"]
ok(len(sh) == 1 and sh[0]["name"] == "Recat TikTok", "users see the published preset")
ok(c.put(f"/api/presets/{aid}", json={"name": "hack", "settings": {}}, headers=H["bob"]).status_code == 404, "users cannot change an admin preset")
ok(len(c.get("/api/presets", headers=H["amy"]).json()["mine"]) == 5, "admin presets do not count toward the 5")
with Session() as s:
    acts = [a.action for a in s.query(AuditLog).all()]
ok("preset.create" in acts and "preset.update" in acts, "audit log")
ok(c.delete(f"/api/admin/presets/{aid}", headers=H["boss"]).status_code == 200 and c.get("/api/presets", headers=H["bob"]).json()["shared"] == [], "admin delete")

# ---- re-render price ----
src = f"{tmp}/up/src.mp4"
open(src, "wb").write(b"x")
project = {"source_duration": 600.0, "voice": "Kore", "fx": {}, "segments": [{"id": 1, "start": 0.0, "end": 5.0, "text": "hello", "source_text": "", "speaker": None}]}
with Session() as s:
    amy = s.query(User).filter_by(email="amy").one()
    s.add(Job(id="orig00000001", user_id=amy.id, status="done", params={"output": "subtitles"}, data={"result": {"project": project}}, input_key=src, charged_seconds=600.0))
    s.commit()
body = {"segments": [{"id": 1, "start": 0.0, "text": "changed"}]}
q = c.get("/api/jobs/orig00000001/edit-price", headers=H["amy"]).json()
ok(q["free_left"] == 3 and q["cost_minutes"] == 0, "3 free re-renders at the start")
for i in range(3):
    r = c.post("/api/jobs/orig00000001/rerender", json=body, headers=H["amy"])
    ok(r.status_code == 200, f"free re-render {i + 1}")
    with Session() as s:
        j = s.get(Job, r.json()["job_id"])
        ok((j.charged_seconds, j.credit_seconds) == (0, 0), "  charged nothing")
        j.status = "done"      # finished, so it counts and the next one can start (max 2 active)
        s.commit()
q = c.get("/api/jobs/orig00000001/edit-price", headers=H["amy"]).json()
ok(q["free_left"] == 0 and q["cost_minutes"] == 4 and q["cost_seconds"] == 240, "4th re-render of a 10 min video = 40% = 4 min")
r = c.post("/api/jobs/orig00000001/rerender", json={**body, "fallback": True}, headers=H["amy"])
with Session() as s:
    j = s.get(Job, r.json()["job_id"])
    ok(r.status_code == 200 and j.charged_seconds == 0, "device-render fallback is free")
    j.status = "done"; s.commit()
ok(c.get("/api/jobs/orig00000001/edit-price", headers=H["amy"]).json()["cost_minutes"] == 4, "fallback is not counted either")
r = c.post("/api/jobs/orig00000001/rerender", json=body, headers=H["amy"])
with Session() as s:
    j = s.get(Job, r.json()["job_id"])
    ok(r.status_code == 200 and j.charged_seconds == 240 and j.credit_seconds == 0, "4th re-render is charged 4 min from the allowance")
    j.status = "done"; s.commit()
# short video: 2 min -> 40% = 0.8 -> rounded up to 1 min
project2 = {**project, "source_duration": 120.0}
with Session() as s:
    s.add(Job(id="orig00000002", user_id=amy.id, status="done", params={"output": "subtitles"}, data={"result": {"project": project2}}, input_key=src + "2", charged_seconds=120.0))
    s.commit()
open(src + "2", "wb").write(b"x")
with Session() as s:
    for i in range(3):
        s.add(Job(id=f"e2{i:010d}", user_id=amy.id, status="done", params={"edit": {"segments": []}}, data={}, input_key=src + "2"))
    s.commit()
ok(c.get("/api/jobs/orig00000002/edit-price", headers=H["amy"]).json()["cost_minutes"] == 1, "2 min video: 0.8 rounds up to 1 min")
# no minutes -> 402
with Session() as s:
    u = s.query(User).filter_by(email="amy").one(); u.daily_minutes = 0; u.credit_seconds = 0; s.commit()
r = c.post("/api/jobs/orig00000002/rerender", json=body, headers=H["amy"])
ok(r.status_code == 402, "no minutes left: 402")
with Session() as s:
    u = s.query(User).filter_by(email="amy").one(); u.credit_seconds = 90; s.commit()
r = c.post("/api/jobs/orig00000002/rerender", json=body, headers=H["amy"])
with Session() as s:
    j = s.get(Job, r.json()["job_id"]); u = s.query(User).filter_by(email="amy").one()
    ok(r.status_code == 200 and j.credit_seconds == 60 and abs(u.credit_seconds - 30) < 1e-6, "paid with bought minutes when the allowance is gone")
ok(c.get("/api/jobs/orig00000001/edit-price", headers=H["bob"]).status_code == 404, "someone else's video: 404")

# ---- previous settings ----
ok(c.get("/api/presets/last", headers=H["bob"]).json()["settings"] is None, "no previous video: nothing")
with Session() as s:
    bob = s.query(User).filter_by(email="bob").one()
    s.add(Job(id="prev00000001", user_id=bob.id, status="done", params={"aspect": "9:16", "fit_mode": "crop", "resolution": 1080, "output": "dub", "enable_subtitles": False, "mode": "full",
             "voice_quality": "premium", "voice_type": "Kore", "enable_flip": True, "brightness": 0.2, "caption_style": {"font": "serif", "color": "#ffffff"}, "background": "separate", "filename": "a.mp4"},
             data={}, input_key="x", charged_seconds=60))
    s.add(Job(id="prev00000002", user_id=bob.id, status="done", params={"edit": {"segments": []}, "aspect": "1:1"}, data={}, input_key="x"))   # a re-render must not count
    s.commit()
last = c.get("/api/presets/last", headers=H["bob"]).json()
st = last["settings"]
ok(st["aspect"] == "9:16" and st["resolution"] == "1080" and st["outputKind"] == "voice" and st["filmMode"] == "full" and st["flip"] is True, "last NEW video's settings, re-renders skipped")
ok(st["voiceType"] == "Kore" and st["captionStyle"]["font"] == "serif" and last["title"] == "a.mp4", "voice, caption style and title")
ok(c.get("/api/presets/last", headers=H["amy"]).json()["settings"] is None, "another user does not get them")
print("ALL OK")
