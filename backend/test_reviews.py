"""Offline: optional star reviews (user gives, only admins read). Run: venv/bin/python test_reviews.py"""
import os, sys, tempfile
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db", TTS_PROVIDER="fake",
                  DUB_PROVIDER="fake", ALLOW_SIGNUP="true", REDIS_URL="", STORAGE_BACKEND="local")
for d in ("data", "up", "out"): os.makedirs(f"{tmp}/{d}")
from fastapi.testclient import TestClient
import main
from db import Job, Session, User
bad = 0
def ok(c, what):
    global bad
    print(("ok   " if c else "FAIL ") + what); bad += 0 if c else 1
c = TestClient(main.app)
def user(name):
    r = c.post("/api/auth/register", json={"email": name, "password": "password123"})
    return {"Authorization": "Bearer " + r.json()["token"]}
a, b, adm = user("amy@example.com"), user("bob@example.com"), user("boss@example.com")
with Session() as s:
    s.query(User).filter_by(email="boss@example.com").one().is_admin = True
    uid = s.query(User).filter_by(email="amy@example.com").one().id
    res = {"video_file": "x.mp4", "timeline": [], "project": {"source_duration": 90, "segments": []}}
    s.add(Job(id="v1", user_id=uid, status="done", params={"filename": "film.mp4", "mode": "full", "voice_quality": "standard", "device_render": True}, data={"result": res, "run_seconds": 120}))
    s.add(Job(id="v2", user_id=uid, status="done", params={"edit": {"x": 1}}, data={"result": res}))
    s.add(Job(id="v3", user_id=uid, status="running", params={}, data={}))
    s.commit()
adm = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "boss@example.com", "password": "password123"}).json()["token"]}
view = lambda j: c.get(f"/api/jobs/{j}", headers=a).json()
ok(view("v1")["review_wanted"] is True, "a finished new video asks for a review")
ok(view("v2")["review_wanted"] is False and view("v3")["review_wanted"] is False, "an edit and a running video do not ask")
post = lambda j, h, body: c.post(f"/api/jobs/{j}/review", headers=h, json=body)
ok(post("v1", b, {"stars": 5}).status_code == 404, "nobody reviews another user's video")
ok(post("v1", a, {"stars": 0}).status_code == 422 and post("v1", a, {"stars": 6}).status_code == 422, "stars must be 1-5")
ok(post("v1", a, {"stars": 5, "text": "x" * 1001}).status_code == 422, "text over 1000 characters is refused")
ok(post("v3", a, {"stars": 5}).status_code == 409, "no review for an unfinished video")
ok(post("v1", a, {"stars": 4, "text": "  good voice  "}).status_code == 200, "a review is accepted (text optional)")
ok(view("v1")["review_wanted"] is False, "it is not asked again")
ok(post("v1", a, {"stars": 2, "text": ""}).status_code == 200, "a second submit replaces the first")
ok(c.get("/api/admin/reviews", headers=a).status_code == 403 and c.get("/api/admin/reviews").status_code == 401, "only admins can read reviews")
ok("review" not in str(c.get("/api/jobs", headers=b).json()).lower(), "other users see nothing of it")
post("v2", a, {"stars": 5, "text": "great"})
r = c.get("/api/admin/reviews", headers=adm).json()
one = next(i for i in r["items"] if i["video"]["id"] == "v1")
ok(r["count"] == 2 and r["average"] == 3.5 and r["by_stars"]["5"] == 1 and r["by_stars"]["2"] == 1, "admin: count, average, stars breakdown")
ok(one["stars"] == 2 and one["text"] == "" and one["user"]["email"] == "amy@example.com", "admin: stars, text and the user")
v = one["video"]
ok(v["title"] == "film.mp4" and v["mode"] == "full" and v["voice_quality"] == "standard" and v["device_render"] and v["minutes"] == 1.5 and v["run_seconds"] == 120, "admin: video info")
ok(c.get("/api/admin/reviews?stars=5", headers=adm).json()["total"] == 1, "admin: filter by stars")
with Session() as s:
    s.delete(s.get(User, uid)); s.commit()
r = c.get("/api/admin/reviews", headers=adm).json()
ok(r["count"] == 2 and all(i["user"]["email"] == "amy@example.com" and i["user"]["deleted"] for i in r["items"]), "reviews stay readable after the account is deleted")
print("ALL OK" if not bad else f"{bad} FAILED"); sys.exit(1 if bad else 0)
