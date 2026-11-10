"""Limits on the editor actions that spend voice requests: live line previews and re-renders.
Both were free and unmetered (a re-render can voice up to 600 lines; the old preview limit lived in process memory), so one account
could use up the shared voice quota (about 100 requests a day per model) and make every other user's upload fail with "server busy".

Counted in the DATABASE (survives restarts, shared by all API processes), per user per UTC day and per source video (a re-render of a
re-render still counts against the original video). Checked and recorded under the same admission lock as uploads, so parallel clicks
cannot all pass. Env: PREVIEWS_PER_VIDEO=20, PREVIEWS_PER_DAY=60, RERENDERS_PER_VIDEO=10, RERENDERS_PER_DAY=30 (doubled on request, 2026-11-10)."""
import os

from fastapi import HTTPException
from sqlalchemy import func, select

import capacity
from db import EditUse, Session, lock_admission, utcnow

LIMITS = {   # kind -> (per video, per day, what the user sees)
    "preview": (int(os.getenv("PREVIEWS_PER_VIDEO", "20")), int(os.getenv("PREVIEWS_PER_DAY", "60")), "voice previews"),
    "rerender": (int(os.getenv("RERENDERS_PER_VIDEO", "10")), int(os.getenv("RERENDERS_PER_DAY", "30")), "re-renders"),
}


def video_id(job) -> str:
    """The original video a job belongs to: re-renders carry it in params.bg_source_job."""
    return (job.params or {}).get("bg_source_job") or job.id


def _count(s, kind: str, user_id: int, vid: str | None = None, since=None) -> int:
    q = select(func.count()).select_from(EditUse).where(EditUse.kind == kind)
    q = q.where(EditUse.user_id == user_id) if vid is None else q.where(EditUse.video_id == vid)
    if since is not None:
        q = q.where(EditUse.created_at >= since)
    return int(s.execute(q).scalar_one())


def record(s, user_id: int, vid: str, kind: str) -> EditUse:
    """Refuse (429) when the user is over a limit, else add one use to session `s` (the caller commits it with its own change).
    Call inside capacity.lock + lock_admission(s)."""
    per_video, per_day, label = LIMITS[kind]
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if _count(s, kind, user_id, vid=vid) >= per_video:
        raise HTTPException(status_code=429, detail=f"You have used all {per_video} {label} for this video. Try again with a new video.")
    if _count(s, kind, user_id, since=day) >= per_day:
        raise HTTPException(status_code=429, detail=f"Daily limit reached ({per_day} {label} a day). Try again tomorrow.")
    use = EditUse(user_id=user_id, video_id=vid, kind=kind)
    s.add(use)
    return use


def charge(user_id: int, vid: str, kind: str) -> int:
    """Own transaction: check the limits and record one use. Returns its id (so a failed request can give it back with refund)."""
    with Session() as s:
        with capacity.lock:
            lock_admission(s)
            use = record(s, user_id, vid, kind)
            s.commit()
            return use.id


def refund(use_id: int) -> None:
    with Session() as s:
        use = s.get(EditUse, use_id)
        if use is not None:
            s.delete(use)
            s.commit()
