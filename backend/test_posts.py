"""Offline test: posts (banners made by admins, shown to users): create / change / delete, status + schedule, picture checks, who may do what, audit.
Run: python test_posts.py"""
import os
import tempfile
from datetime import timedelta

tmp = tempfile.mkdtemp()
os.environ.update(AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
for d in ("data", "up", "out"):
    os.makedirs(f"{tmp}/{d}", exist_ok=True)

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from db import AuditLog, Session, User, utcnow  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


with Session() as s:
    s.add_all([User(email="boss", password_hash="x", is_admin=True, is_superadmin=True), User(email="helper", password_hash="x", is_admin=True), User(email="amy", password_hash="x")])
    s.commit()
    H = {u.email: {"Authorization": f"Bearer {auth.make_token(u)}"} for u in s.query(User).all()}
c = TestClient(main.app)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50
pic = lambda: {"image": ("b.png", PNG, "image/png")}
iso = lambda dt: dt.isoformat()
now = utcnow()
shown = lambda: [p["title"] for p in c.get("/api/posts", headers=H["amy"]).json()["posts"]]

ok(c.get("/api/admin/posts", headers=H["amy"]).status_code == 403 and c.post("/api/admin/posts", headers=H["amy"], data={"title": "x"}).status_code == 403, "a normal user cannot see or make posts")
ok(c.get("/api/posts").status_code == 401, "the banner list needs a login")
r = c.post("/api/admin/posts", headers=H["helper"], data={"title": "Draft one", "body": "hello"})
ok(r.status_code == 200 and r.json()["state"] == "draft" and r.json()["image_url"] is None, "an ADMIN (not only the superadmin) can make a draft, even without a picture")
draft = r.json()["id"]
ok(c.post("/api/admin/posts", headers=H["boss"], data={"title": "No pic", "status": "published"}).status_code == 400, "publishing without a picture is refused")
ok(c.post("/api/admin/posts", headers=H["boss"], data={"title": "Bad", "status": "published"}, files={"image": ("x.png", b"not a picture", "image/png")}).status_code == 400, "a file that is not a picture is refused")
ok(c.post("/api/admin/posts", headers=H["boss"], data={"title": " ", "status": "draft"}).status_code == 400, "a title is needed")
ok(c.post("/api/admin/posts", headers=H["boss"], data={"title": "L", "link_url": "javascript:alert(1)"}).status_code == 400, "only http(s) links")
ok(c.post("/api/admin/posts", headers=H["boss"], data={"title": "T", "starts_at": iso(now), "ends_at": iso(now - timedelta(hours=1))}).status_code == 400, "end before start is refused")

live = c.post("/api/admin/posts", headers=H["boss"], data={"title": "Live now", "status": "published", "link_url": "https://example.com/x"}, files=pic()).json()
soon = c.post("/api/admin/posts", headers=H["boss"], data={"title": "Next week", "status": "published", "starts_at": iso(now + timedelta(days=7))}, files=pic()).json()
past = c.post("/api/admin/posts", headers=H["boss"], data={"title": "Last week", "status": "published", "starts_at": iso(now - timedelta(days=9)), "ends_at": iso(now - timedelta(days=2))}, files=pic()).json()
window = c.post("/api/admin/posts", headers=H["boss"], data={"title": "This week", "status": "published", "starts_at": iso(now - timedelta(days=1)), "ends_at": iso(now + timedelta(days=1))}, files=pic()).json()
ok([live["state"], soon["state"], past["state"], window["state"]] == ["live", "scheduled", "ended", "live"], "state follows status + schedule: live, scheduled, ended, live")
ok(shown() == ["Live now", "This week"], f"users see only the live ones, newest start first: {shown()}")
u = c.get("/api/posts", headers=H["amy"]).json()["posts"][0]
ok(set(u) == {"id", "title", "body", "link_url", "image_url"} and u["link_url"] == "https://example.com/x", "users get only what the banner needs")
img = c.get(u["image_url"])
ok(img.status_code == 200 and img.content == PNG and img.headers["content-type"] == "image/png", "the picture opens without a login (an <img> cannot send one)")
ok(c.get("/api/posts/image/..%2Fapp.db").status_code == 404 and c.get("/api/posts/image/secret.key").status_code == 404, "only post pictures can be fetched there")

# change: status off hides it, publishing the draft needs a picture, a new picture replaces the old file
r = c.post(f"/api/admin/posts/{live['id']}", headers=H["helper"], data={"title": "Live now", "status": "off", "link_url": "https://example.com/x"})
ok(r.json()["state"] == "off" and shown() == ["This week"], "status off hides a post at once")
ok(c.post(f"/api/admin/posts/{draft}", headers=H["boss"], data={"title": "Draft one", "status": "published"}).status_code == 400, "a draft without a picture cannot be published")
r = c.post(f"/api/admin/posts/{draft}", headers=H["boss"], data={"title": "Now public", "status": "published"}, files=pic())
ok(r.status_code == 200 and r.json()["state"] == "live" and "Now public" in shown(), "draft + picture -> published -> users see it")
first = r.json()["image_url"].rsplit("/", 1)[1]
r = c.post(f"/api/admin/posts/{draft}", headers=H["boss"], data={"title": "Now public", "status": "published"}, files=pic())
second = r.json()["image_url"].rsplit("/", 1)[1]
ok(first != second and not os.path.exists(f"{tmp}/data/posts/{first}") and os.path.exists(f"{tmp}/data/posts/{second}"), "a new picture replaces the old file")
r = c.post(f"/api/admin/posts/{soon['id']}", headers=H["boss"], data={"title": "Next week", "status": "published", "starts_at": iso(now - timedelta(minutes=1))})
ok(r.json()["state"] == "live" and r.json()["image_url"] == soon["image_url"], "moving the start time makes a scheduled post live; the picture is kept when none is sent")
ok(c.post("/api/admin/posts/9999", headers=H["boss"], data={"title": "x"}).status_code == 404, "unknown post -> 404")

lst = c.get("/api/admin/posts", headers=H["helper"]).json()
ok(lst["total"] == 5 and lst["items"][0]["id"] == window["id"], "admin list: all posts, newest first")
ok(c.delete(f"/api/admin/posts/{draft}", headers=H["helper"]).status_code == 200 and not os.path.exists(f"{tmp}/data/posts/{second}") and "Now public" not in shown(), "delete removes the post and its picture")
ok(c.delete(f"/api/admin/posts/{draft}", headers=H["helper"]).status_code == 404, "deleting twice -> 404")
with Session() as s:
    acts = [a.action for a in s.query(AuditLog).order_by(AuditLog.id).all()]
    one = s.query(AuditLog).filter_by(action="post.update").first()
ok(acts.count("post.create") == 5 and acts.count("post.update") == 4 and acts.count("post.delete") == 1, f"audit log: every successful change, nothing for refused ones ({len(acts)})")
ok(one.details == {"status": {"from": "published", "to": "off"}}, "audit keeps only what changed")
print("all post tests passed")
