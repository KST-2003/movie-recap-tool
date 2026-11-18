"""Unlock requests: a user paused after FAIL_STREAK failed / cancelled videos in a row can ask an admin to review it instead of waiting the whole pause.
Admin side (list / approve / reject) lives in admin/routes.py. Approving sets users.fail_reset_at, so the failed videos before it stop counting."""
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

import alerts
import auth
from db import FAIL_BLOCK_HOURS, Session, UnlockRequest, User, failure_wait_seconds, utcnow

router = APIRouter()


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def latest_for_current_pause(s, user_id: int):
    """The user's newest request made during the current pause (a pause lasts FAIL_BLOCK_HOURS, so only recent requests belong to it)."""
    since = utcnow() - timedelta(hours=max(FAIL_BLOCK_HOURS, 0.1))
    return s.execute(select(UnlockRequest).where(UnlockRequest.user_id == user_id, UnlockRequest.created_at >= since)
                     .order_by(UnlockRequest.id.desc()).limit(1)).scalar_one_or_none()


def view(row) -> dict | None:
    if row is None:
        return None
    return {"id": row.id, "status": row.status, "note": row.note, "admin_note": row.admin_note,
            "created_at": _aware(row.created_at).isoformat() if row.created_at else None,
            "decided_at": _aware(row.decided_at).isoformat() if row.decided_at else None}


def state_for(s, user) -> dict | None:
    """What /api/auth/me shows: the user's request during the current pause (None when not paused or never asked)."""
    if user.is_admin or failure_wait_seconds(s, user.id) <= 0:
        return None
    return view(latest_for_current_pause(s, user.id))


class AskBody(BaseModel):
    note: str = Field("", max_length=300)


@router.post("/api/unlock-request")
def ask_for_review(body: AskBody, user: User = Depends(auth.current_user)):
    with Session() as s:
        if user.is_admin or failure_wait_seconds(s, user.id) <= 0:
            raise HTTPException(status_code=400, detail="Your uploads are not paused, so there is nothing to review.")
        last = latest_for_current_pause(s, user.id)
        if last is not None and last.status == "pending":
            raise HTTPException(status_code=409, detail="Your request was already sent. The admin will review it soon.")
        if last is not None and last.status == "rejected":
            raise HTTPException(status_code=429, detail="The admin reviewed your request and did not unlock it. Please wait until the pause ends.")
        row = UnlockRequest(user_id=user.id, user_label=user.email, note=body.note.strip()[:300] or None)
        s.add(row)
        s.commit()
        s.refresh(row)
        out = view(row)
    alerts.raise_alert(f"unlock:{user.id}", f"User {user.email} asked an admin to review their paused uploads (Unlock requests page).")
    return out
