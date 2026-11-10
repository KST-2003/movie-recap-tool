"""Account routes: register, login, refresh, logout, logout-all, /me, /usage.
Split out of main.py; nothing here changed behaviour, only location."""
import re
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

import auth
import ratelimit
from config import ALLOW_SIGNUP, SIGNUP_DAILY_MINUTES, SIGNUP_MAX_PER_DAY, SIGNUP_MONTHLY_MINUTES
from db import Job, Session, User, month_start, utcnow
from services.quota import quota_view

router = APIRouter(prefix="/api", tags=["accounts"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Credentials(BaseModel):
    email: str
    password: str
    audience: str = "app"   # "admin" = the owner dashboard (needs an admin account and the dashboard's origin)
    cookie: bool = False    # True = browser apps: the session goes into an httpOnly cookie and the body carries only a CSRF token; False = the token is in the body


def _session_reply(request: Request, response: Response, user: User, payload: dict, audience: str, cookie: bool) -> dict:
    token = auth.make_token(user, audience=audience)
    if cookie:
        auth.set_session_cookie(response, request, token, audience)
        payload["csrf_token"] = auth.csrf_for(token)
    else:
        payload["token"] = token
    return payload


@router.post("/auth/register")
def register(body: Credentials, request: Request, response: Response):
    ratelimit.register_attempt(request)
    ratelimit.check_password_length(body.password)
    if body.cookie:
        auth.check_issue_origin(request, "app")
    if not ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="Sign-ups are closed.")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    password_hash = auth.hash_password(body.password)   # slow on purpose: done before taking the lock
    import capacity
    from db import lock_admission
    with Session() as s:
        with capacity.lock:   # the daily cap is checked and the account created as one step: a burst cannot exceed it
            lock_admission(s)
            if s.execute(select(User).where(User.email == email)).scalar_one_or_none():
                raise HTTPException(status_code=409, detail="That email is already registered.")
            if SIGNUP_MAX_PER_DAY:
                import alerts
                today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                made = s.execute(select(func.count()).select_from(User).where(User.created_at >= today)).scalar_one()
                if made >= SIGNUP_MAX_PER_DAY:
                    alerts.raise_alert("signups", f"{made} accounts were created today (limit {SIGNUP_MAX_PER_DAY}): new sign-ups are paused until tomorrow. "
                                                  "Raise SIGNUP_MAX_PER_DAY if this is real growth, otherwise someone is mass-registering.")
                    raise HTTPException(status_code=503, detail="Sign-ups are very busy today. Please try again tomorrow.")
            user = User(email=email, password_hash=password_hash, daily_minutes=SIGNUP_DAILY_MINUTES, monthly_minutes=SIGNUP_MONTHLY_MINUTES)
            s.add(user)
            s.commit()
    return _session_reply(request, response, user, {"email": email, "is_admin": False, **quota_view(user)}, "app", body.cookie)


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response):
    ratelimit.check_password_length(body.password)
    audience = "admin" if body.audience == "admin" else "app"
    if body.cookie:
        auth.check_issue_origin(request, audience)
    email = body.email.strip().lower()[:255]
    keys = ratelimit.login_attempt(request, email)   # counted BEFORE the password check; a correct password gives it back
    with Session() as s:
        user = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
    password_ok = auth.verify_password(body.password, user.password_hash if user else auth.DUMMY_HASH)   # same work for unknown emails
    if not user or not user.is_active or not password_ok:
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    ratelimit.login_succeeded(keys)
    if audience == "admin" and not user.is_admin:
        raise HTTPException(status_code=403, detail="This account is not an admin.")
    if auth.needs_rehash(user.password_hash):   # old, cheaper hash: store a stronger one now that we hold the password
        upgraded = auth.hash_password(body.password)
        with Session() as s:
            row = s.get(User, user.id)
            if row is not None and row.password_hash == user.password_hash:   # not if the password was changed meanwhile
                row.password_hash = upgraded
                s.commit()
    return _session_reply(request, response, user, {"email": user.email, "is_admin": user.is_admin, **quota_view(user)}, audience, body.cookie)


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, creds=Depends(auth._bearer)):
    """A new token for a valid one. The apps call it every few minutes while open, which is what lets admin tokens be short.
    A cookie session gets a new cookie and a new CSRF token; a bearer session gets the new token in the body."""
    user, token, via, audience = auth.renewed_token(request, creds)
    if via == "cookie":
        auth.set_session_cookie(response, request, token, audience)
        return {"csrf_token": auth.csrf_for(token), "is_admin": user.is_admin}
    return {"token": token, "is_admin": user.is_admin}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    """Forget this browser's session cookie. (JavaScript cannot delete an httpOnly cookie, the server has to.) Needs no login: logging out must
    always work, even with an expired session."""
    auth.clear_session_cookie(response, request, auth.audience_of(request.headers))
    return {"ok": True}


@router.post("/auth/logout-all")
def logout_all(request: Request, response: Response, user: User = Depends(auth.current_user)):
    """Cancel every session of this account (this device and all others)."""
    with Session() as s:
        row = s.get(User, user.id)
        auth.revoke_tokens(s, row)
        s.commit()
    auth.clear_session_cookie(response, request, auth.audience_of(request.headers))
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request, user: User = Depends(auth.current_user)):
    out = {"id": user.id, "email": user.email, "is_admin": user.is_admin, **quota_view(user)}
    if request.state.auth_via == "cookie":   # a page reload lost the CSRF token held in memory: hand it out again (only an allowed origin can read this answer)
        out["csrf_token"] = auth.csrf_for(request.state.token)
    return out


@router.get("/usage")
def usage(user: User = Depends(auth.current_user)):
    """The signed-in user's own usage: totals, 30 days of minutes, and their recent videos (for their dashboard)."""
    now = utcnow()
    days = 30
    first = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session() as s:
        rows = s.execute(select(Job).where(Job.user_id == user.id, Job.created_at >= min(first, month_start()))
                         .order_by(Job.created_at.desc())).scalars().all()
        recent = s.execute(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(20)).scalars().all()
        total_videos = s.execute(select(func.count()).select_from(Job).where(Job.user_id == user.id, Job.status == "done")).scalar_one()
    per_day: dict[str, float] = {}
    by_kind = {"recap": 0.0, "full": 0.0, "subtitles": 0.0}
    month_videos = 0
    for j in rows:
        created = j.created_at if j.created_at.tzinfo else j.created_at.replace(tzinfo=timezone.utc)
        if created >= first:
            key = created.strftime("%Y-%m-%d")
            per_day[key] = per_day.get(key, 0.0) + (j.charged_seconds or 0.0) / 60
        if created >= month_start() and (j.charged_seconds or 0) > 0:
            month_videos += 1
            p = j.params or {}
            kind = "subtitles" if p.get("output") == "subtitles" else ("full" if p.get("mode") == "full" else "recap")
            by_kind[kind] += (j.charged_seconds or 0.0) / 60
    series = [{"date": (first + timedelta(days=i)).strftime("%Y-%m-%d"),
               "minutes": round(per_day.get((first + timedelta(days=i)).strftime("%Y-%m-%d"), 0.0), 1)} for i in range(days)]
    nxt_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    nxt_month = (month_start() + timedelta(days=32)).replace(day=1)
    return {
        **quota_view(user), "days": series, "minutes_by_kind": {k: round(v, 1) for k, v in by_kind.items()},
        "month_videos": month_videos, "total_videos": total_videos,
        "resets": {"day": nxt_day.isoformat(), "month": nxt_month.isoformat()},
        "recent": [{"id": j.id, "created_at": (j.created_at if j.created_at.tzinfo else j.created_at.replace(tzinfo=timezone.utc)).isoformat(), "status": j.status,
                    "minutes": round((j.charged_seconds or 0.0) / 60, 1),
                    "kind": "edit" if (j.params or {}).get("edit") else ("subtitles" if (j.params or {}).get("output") == "subtitles"
                                                                          else ("full" if (j.params or {}).get("mode") == "full" else "recap")),
                    "aspect": (j.params or {}).get("aspect", "original")} for j in recent],
    }
