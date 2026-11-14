"""Posts = banners in the user app, made in the admin dashboard (admins and the superadmin).
A post has a 16:9 picture, a title, optional text and link, a status (draft | published | off) and an optional schedule (from / until).
Users see a post while it is LIVE: published, the start time reached and the end time not passed (`state`).
Admin: /api/admin/posts (list, create, change, delete; audit-logged). Users: GET /api/posts (login needed).
Pictures: DATA_DIR/posts, served WITHOUT login at /api/posts/image/<random name> (an <img> cannot send the login; banners are not secret)."""
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

import auth
import topup
from admin.routes import _audit, _iso, require_admin
from config import DATA_DIR
from db import Post, Session, User, utcnow

STATUSES = ("draft", "published", "off")
MAX_IMAGE_MB = 4
MAX_SHOWN = 8          # banners a user gets at once (newest start first)
FOLDER = os.path.join(DATA_DIR, "posts")
_NAME = re.compile(r"^post_[0-9a-f]{16}\.(jpg|png|webp)$")
_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

admin_router = APIRouter(prefix="/api/admin/posts", dependencies=[Depends(require_admin)])
router = APIRouter()


def _aware(dt):
    return None if dt is None else (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)


def state(p: Post, now=None) -> str:
    """draft | off | scheduled (published, not started) | live | ended (published, end time passed)."""
    if p.status != "published":
        return p.status if p.status in STATUSES else "draft"
    now = now or utcnow()
    if p.starts_at and _aware(p.starts_at) > now:
        return "scheduled"
    if p.ends_at and _aware(p.ends_at) <= now:
        return "ended"
    return "live"


def image_url(name):
    return f"/api/posts/image/{name}" if name else None


def row(p: Post, now=None) -> dict:
    return {"id": p.id, "title": p.title, "body": p.body or "", "link_url": p.link_url or "", "image_url": image_url(p.image_file),
            "status": p.status, "state": state(p, now), "starts_at": _iso(p.starts_at), "ends_at": _iso(p.ends_at),
            "created_by": p.created_by, "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at)}


def _time(text: str, label: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{label}: not a valid date and time.")
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def _clean(title, body, link_url, status):
    title, body, link_url = (title or "").strip(), (body or "").strip(), (link_url or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Give the post a title.")
    if len(title) > 120 or len(body) > 600 or len(link_url) > 500:
        raise HTTPException(status_code=400, detail="The title, text or link is too long.")
    if link_url and not re.match(r"^https?://[^\s]+$", link_url):
        raise HTTPException(status_code=400, detail="The link must start with http:// or https://")
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    return title, body, link_url


def _save_image(upload: UploadFile) -> str:
    data, kind = topup.read_image(upload, MAX_IMAGE_MB, allow_pdf=False)
    os.makedirs(FOLDER, exist_ok=True)
    name = f"post_{uuid.uuid4().hex[:16]}.{kind}"
    with open(os.path.join(FOLDER, name), "wb") as f:
        f.write(data)
    return name


def _remove_image(name):
    if name and _NAME.match(name):
        try:
            os.remove(os.path.join(FOLDER, name))
        except OSError:
            pass


def _check(status, start, end, has_image: bool):
    if start and end and end <= start:
        raise HTTPException(status_code=400, detail="The end time must be after the start time.")
    if status == "published" and not has_image:
        raise HTTPException(status_code=400, detail="Upload a picture before publishing.")


@admin_router.get("")
def list_posts(page: int = 1, per_page: int = 25):
    per_page, page = min(max(per_page, 1), 100), max(page, 1)
    now = utcnow()
    with Session() as s:
        total = s.execute(select(func.count()).select_from(Post)).scalar_one()
        rows = s.execute(select(Post).order_by(Post.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
        return {"total": total, "page": page, "per_page": per_page, "items": [row(p, now) for p in rows]}


@admin_router.post("")
def create_post(title: str = Form(...), body: str = Form(""), link_url: str = Form(""), status: str = Form("draft"),
                starts_at: str = Form(""), ends_at: str = Form(""), image: UploadFile | None = File(None), admin: User = Depends(require_admin)):
    title, body, link_url = _clean(title, body, link_url, status)
    p = Post(title=title, body=body, link_url=link_url, status=status, starts_at=_time(starts_at, "Start"), ends_at=_time(ends_at, "End"), created_by=admin.email)
    _check(status, p.starts_at, p.ends_at, image is not None)
    p.image_file = _save_image(image) if image is not None else None
    with Session() as s:
        s.add(p)
        s.flush()
        _audit(s, admin, "post.create", "post", p.id, p.title, {"status": p.status, "starts_at": _iso(p.starts_at), "ends_at": _iso(p.ends_at)})
        s.commit()
        return row(p)


@admin_router.post("/{post_id}")
def update_post(post_id: int, title: str = Form(...), body: str = Form(""), link_url: str = Form(""), status: str = Form("draft"),
                starts_at: str = Form(""), ends_at: str = Form(""), image: UploadFile | None = File(None), admin: User = Depends(require_admin)):
    title, body, link_url = _clean(title, body, link_url, status)
    start, end = _time(starts_at, "Start"), _time(ends_at, "End")
    with Session() as s:
        p = s.get(Post, post_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Unknown post.")
        before = {"title": p.title, "body": p.body or "", "link_url": p.link_url or "", "status": p.status, "starts_at": _iso(p.starts_at), "ends_at": _iso(p.ends_at)}
        p.title, p.body, p.link_url, p.status, p.starts_at, p.ends_at = title, body, link_url, status, start, end
        _check(status, start, end, bool(p.image_file) or image is not None)
        old = None
        if image is not None:
            old, p.image_file = p.image_file, _save_image(image)
        after = {"title": p.title, "body": p.body or "", "link_url": p.link_url or "", "status": p.status, "starts_at": _iso(p.starts_at), "ends_at": _iso(p.ends_at)}
        changed = {k: {"from": before[k], "to": after[k]} for k in after if before[k] != after[k]}
        if image is not None:
            changed["image"] = {"from": bool(old), "to": True}
        if changed:
            p.updated_at = utcnow()
            _audit(s, admin, "post.update", "post", p.id, p.title, changed)
        s.commit()
        _remove_image(old)
        return row(p)


@admin_router.delete("/{post_id}")
def delete_post(post_id: int, admin: User = Depends(require_admin)):
    with Session() as s:
        p = s.get(Post, post_id)
        if p is None:
            raise HTTPException(status_code=404, detail="Unknown post.")
        name = p.image_file
        _audit(s, admin, "post.delete", "post", p.id, p.title, {"status": p.status})
        s.delete(p)
        s.commit()
    _remove_image(name)
    return {"ok": True}


@router.get("/api/posts")
def live_posts(user: User = Depends(auth.current_user)):
    """The banners to show right now (newest start first)."""
    now = utcnow()
    with Session() as s:
        rows = s.execute(select(Post).where(Post.status == "published").order_by(Post.id.desc()).limit(200)).scalars().all()
        live = [p for p in rows if state(p, now) == "live" and p.image_file]
        live.sort(key=lambda p: (_aware(p.starts_at) or _aware(p.created_at) or now, p.id), reverse=True)
        return {"posts": [{"id": p.id, "title": p.title, "body": p.body or "", "link_url": p.link_url or "", "image_url": image_url(p.image_file)} for p in live[:MAX_SHOWN]]}


@router.get("/api/posts/image/{name}")
def post_image(name: str):
    path = os.path.join(FOLDER, name)
    if not _NAME.match(name) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type=_TYPES[name.rsplit(".", 1)[1]], headers={"Cache-Control": "public, max-age=604800, immutable"})
