"""Reviews: after a video is made the user may rate it (1-5 stars + optional words). Only admins read them (admin "Reviews" page).

One review per video (a second submit replaces the first). Giving one is optional; nothing depends on it."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import auth
from admin.routes import _iso, require_admin
from db import Job, Review, Session, User, utcnow

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin/reviews", dependencies=[Depends(require_admin)])


class ReviewIn(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    text: str = Field("", max_length=1000)


def wanted(job: Job) -> bool:
    """Ask for a review? Only for a finished NEW video (not for every edit of it) that has none yet."""
    if job.status != "done" or (job.params or {}).get("edit"):
        return False
    with Session() as s:
        return s.execute(select(Review.id).where(Review.job_id == job.id)).first() is None


@router.post("/api/jobs/{job_id}/review")
def give_review(job_id: str, body: ReviewIn, user: User = Depends(auth.current_user)):
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job")
        if job.status != "done":
            raise HTTPException(status_code=409, detail="This video is not finished.")
        row = s.execute(select(Review).where(Review.job_id == job_id)).scalar_one_or_none()
        if row is None:
            row = Review(job_id=job_id, user_id=user.id, user_label=user.email)
            s.add(row)
        row.stars, row.text, row.created_at = body.stars, body.text.strip(), utcnow()
        s.commit()
    return {"ok": True}


def _video(job: Job | None) -> dict | None:
    if job is None:
        return None
    p, d = job.params or {}, job.data or {}
    project = (d.get("result") or {}).get("project") or {}
    return {"id": job.id, "title": p.get("filename") or "", "mode": p.get("mode", "recap"), "output": p.get("output", "dub"),
            "voice_quality": p.get("voice_quality", "premium"), "device_render": bool(p.get("device_render")),
            "minutes": round(float(project.get("source_duration") or (job.charged_seconds or 0)) / 60, 1),
            "aspect": p.get("aspect", "original"), "resolution": p.get("resolution"), "from_link": bool(p.get("from_link")),
            "run_seconds": d.get("run_seconds"), "created_at": _iso(job.created_at), "deleted": bool(d.get("user_deleted"))}


@admin_router.get("")
def list_reviews(page: int = 1, per_page: int = 25, stars: int = 0):
    per_page, page = min(max(per_page, 1), 100), max(page, 1)
    with Session() as s:
        where = [Review.stars == stars] if 1 <= stars <= 5 else []
        total = s.execute(select(func.count()).select_from(Review).where(*where)).scalar_one()
        count, avg = s.execute(select(func.count(), func.avg(Review.stars)).select_from(Review)).one()
        by = dict(s.execute(select(Review.stars, func.count()).group_by(Review.stars)).all())
        rows = s.execute(select(Review).where(*where).order_by(Review.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
        users = {u.id: u for u in s.execute(select(User).where(User.id.in_({r.user_id for r in rows}))).scalars()} if rows else {}
        jobs = {j.id: j for j in s.execute(select(Job).where(Job.id.in_({r.job_id for r in rows}))).scalars()} if rows else {}
        items = [{"id": r.id, "stars": r.stars, "text": r.text or "", "created_at": _iso(r.created_at),
                  "user": {"id": r.user_id, "email": users[r.user_id].email if r.user_id in users else r.user_label, "deleted": r.user_id not in users},
                  "video": _video(jobs.get(r.job_id))} for r in rows]
    return {"total": total, "page": page, "per_page": per_page, "count": count, "average": round(float(avg), 2) if avg is not None else None,
            "by_stars": {str(n): int(by.get(n, 0)) for n in range(5, 0, -1)}, "items": items}
