"""Admin API for the dashboard (/api/admin/*). Every route needs a logged-in user with is_admin = True
(make one with `python manage.py create-user EMAIL PASSWORD --admin`)."""
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import auth
from config import (ALLOW_SIGNUP, DEFAULT_DAILY_MINUTES, DEFAULT_MONTHLY_MINUTES, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES,
                    QUEUE_MODE)
import alerts
import capacity
import usage as usage_log
from . import settings as runtime_settings
from db import AuditLog, Job, Session, User, month_start, update_job, used_seconds_month, used_seconds_today, utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATUSES = ("queued", "running", "done", "error", "cancelled")
AUDIT_ACTIONS = ("user.create", "user.update", "job.cancel", "settings.update")


def require_admin(user: User = Depends(auth.current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


def _audit(s, admin: User, action: str, target_type: str, target_id, target_label: str | None = None, details: dict | None = None):
    """Add an audit row to the session `s`; the caller commits it together with the change itself."""
    s.add(AuditLog(admin_id=admin.id, admin_email=admin.email, action=action, target_type=target_type,
                   target_id=str(target_id), target_label=target_label, details=details or {}))


def _day_start():
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def _iso(dt):
    """ISO time marked as UTC (SQLite hands back naive datetimes, which a browser would read as local time)."""
    if not dt:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()


# ---------- overview ----------

@router.get("/overview")
def overview(days: int = 14):
    days = min(max(days, 1), 90)
    today = _day_start()
    first = today - timedelta(days=days - 1)
    with Session() as s:
        total_users = s.execute(select(func.count()).select_from(User)).scalar_one()
        active_users = s.execute(select(func.count()).select_from(User).where(User.is_active.is_(True))).scalar_one()
        counts_today = dict(s.execute(select(Job.status, func.count()).where(Job.created_at >= today).group_by(Job.status)).all())
        queued = s.execute(select(func.count()).select_from(Job).where(Job.status == "queued")).scalar_one()
        running = s.execute(select(func.count()).select_from(Job).where(Job.status == "running")).scalar_one()
        users_today = s.execute(select(func.count(func.distinct(Job.user_id))).where(Job.created_at >= today)).scalar_one()
        minutes_today = used_seconds_today(s) / 60
        rows = s.execute(select(Job.created_at, Job.status, Job.charged_seconds).where(Job.created_at >= first)).all()
        capacity_status = capacity.status(s)
    series = {(first + timedelta(days=i)).date().isoformat(): {"jobs": 0, "errors": 0, "minutes": 0.0} for i in range(days)}
    for created, status, charged in rows:
        point = series.get(created.date().isoformat())
        if point is None:
            continue
        point["jobs"] += 1
        point["errors"] += status == "error"
        point["minutes"] += (charged or 0) / 60
    cap = runtime_settings.global_daily_minutes()
    return {
        "users": {"total": total_users, "active": active_users, "active_today": users_today},
        "jobs_today": {"total": sum(counts_today.values()), **{k: counts_today.get(k, 0) for k in STATUSES}},
        "queue": {"queued": queued, "running": running, "mode": QUEUE_MODE},
        "minutes_today": round(minutes_today, 1),
        "global_daily_minutes": cap,
        "maintenance": runtime_settings.maintenance(),
        "capacity": capacity_status, "alerts": alerts.active(),
        "series": [{"day": d, "jobs": v["jobs"], "errors": v["errors"], "minutes": round(v["minutes"], 1)} for d, v in series.items()],
    }


# ---------- users ----------

def _user_row(u: User, used_seconds: float, month_seconds: float = 0.0) -> dict:
    return {"id": u.id, "email": u.email, "daily_minutes": u.daily_minutes, "monthly_minutes": u.monthly_minutes,
            "is_admin": u.is_admin, "is_active": u.is_active,
            "created_at": _iso(u.created_at), "used_minutes_today": round(used_seconds / 60, 1),
            "used_minutes_month": round(month_seconds / 60, 1)}


@router.get("/users")
def list_users(q: str = "", page: int = 1, per_page: int = 25):
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    today = _day_start()
    with Session() as s:
        query = select(User)
        count = select(func.count()).select_from(User)
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query, count = query.where(User.email.like(like)), count.where(User.email.like(like))
        total = s.execute(count).scalar_one()
        users = s.execute(query.order_by(User.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
        used = dict(s.execute(select(Job.user_id, func.coalesce(func.sum(Job.charged_seconds), 0.0))
                              .where(Job.created_at >= today, Job.user_id.in_([u.id for u in users]))
                              .group_by(Job.user_id)).all()) if users else {}
        month_used = dict(s.execute(select(Job.user_id, func.coalesce(func.sum(Job.charged_seconds), 0.0))
                                    .where(Job.created_at >= month_start(), Job.user_id.in_([u.id for u in users]))
                                    .group_by(Job.user_id)).all()) if users else {}
    return {"total": total, "page": page, "per_page": per_page,
            "items": [_user_row(u, float(used.get(u.id, 0.0)), float(month_used.get(u.id, 0.0))) for u in users],
            "default_daily_minutes": DEFAULT_DAILY_MINUTES, "default_monthly_minutes": DEFAULT_MONTHLY_MINUTES}


class NewUser(BaseModel):
    email: str
    password: str
    daily_minutes: int = Field(DEFAULT_DAILY_MINUTES, ge=0, le=100000)
    monthly_minutes: int = Field(DEFAULT_MONTHLY_MINUTES, ge=0, le=3000000)
    is_admin: bool = False


@router.post("/users")
def create_user(body: NewUser, admin: User = Depends(require_admin)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with Session() as s:
        if s.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise HTTPException(status_code=409, detail="That email is already registered.")
        user = User(email=email, password_hash=auth.hash_password(body.password), daily_minutes=body.daily_minutes, monthly_minutes=body.monthly_minutes, is_admin=body.is_admin)
        s.add(user)
        s.flush()
        _audit(s, admin, "user.create", "user", user.id, user.email, {"daily_minutes": user.daily_minutes, "monthly_minutes": user.monthly_minutes, "is_admin": user.is_admin})
        s.commit()
        return _user_row(user, 0.0)


class UserPatch(BaseModel):
    daily_minutes: int | None = Field(None, ge=0, le=100000)
    monthly_minutes: int | None = Field(None, ge=0, le=3000000)
    is_active: bool | None = None
    is_admin: bool | None = None
    password: str | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin)):
    if user_id == admin.id and (body.is_active is False or body.is_admin is False):
        raise HTTPException(status_code=400, detail="You cannot disable or demote your own account.")
    if body.password is not None and len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        changes = {}
        for field in ("daily_minutes", "monthly_minutes", "is_active", "is_admin"):
            new = getattr(body, field)
            if new is not None and new != getattr(user, field):
                changes[field] = {"from": getattr(user, field), "to": new}
                setattr(user, field, new)
        if body.password is not None:
            user.password_hash = auth.hash_password(body.password)
            changes["password_reset"] = True   # the password itself is never stored in the log
        if changes:
            _audit(s, admin, "user.update", "user", user.id, user.email, changes)
        s.commit()
        return _user_row(user, used_seconds_today(s, user.id), used_seconds_month(s, user.id))


# ---------- jobs ----------

@router.get("/jobs")
def list_jobs(status: str = "", user_id: int | None = None, page: int = 1, per_page: int = 25):
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    if status and status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    with Session() as s:
        query = select(Job, User.email).join(User, User.id == Job.user_id)
        count = select(func.count()).select_from(Job)
        if status:
            query, count = query.where(Job.status == status), count.where(Job.status == status)
        if user_id is not None:
            query, count = query.where(Job.user_id == user_id), count.where(Job.user_id == user_id)
        total = s.execute(count).scalar_one()
        rows = s.execute(query.order_by(Job.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    items = []
    table, rate = usage_log.prices(), runtime_settings.usd_thb()
    for job, email in rows:
        params, data = job.params or {}, job.data or {}
        cost = usage_log.cost_thb(data.get("usage"), table, rate) if data.get("usage") else None
        items.append({"cost_thb": round(cost["thb"], 2) if cost else None, "cost_complete": cost["complete"] if cost else None,"id": job.id, "user_id": job.user_id, "email": email, "status": job.status, "stage": job.stage,
                      "progress": job.progress, "error": job.error, "mode": params.get("mode"), "output": params.get("output"),
                      "video_minutes": round((job.charged_seconds or 0) / 60, 1), "run_seconds": data.get("run_seconds"),
                      "created_at": _iso(job.created_at), "finished_at": _iso(job.finished_at)})
    return {"total": total, "page": page, "per_page": per_page, "items": items}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, admin: User = Depends(require_admin)):
    with Session() as s:
        job = s.get(Job, job_id)
        owner = s.get(User, job.user_id) if job else None
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        if job.status not in ("queued", "running"):
            raise HTTPException(status_code=409, detail=f"The job is already {job.status}.")
        _audit(s, admin, "job.cancel", "job", job.id, owner.email if owner else None, {"status": {"from": job.status, "to": "cancelled"}})
        s.commit()
    update_job(job_id, status="cancelled", stage="Cancelled by admin")
    return {"status": "cancelled"}


# ---------- voice (TTS) model pool ----------

@router.get("/tts")
def tts_status(refresh: bool = False):
    import gemini_tts
    import tts_pool
    from . import google_quota
    pool = tts_pool.models()
    verified = google_quota.verify_models(refresh)
    cloud = google_quota.cloud([name for name, _, _ in pool], refresh)
    seen = gemini_tts.limits_seen()
    items = []
    import azure_tts
    import cloud_tts
    for name, rpm, rpd in pool:
        via_cloud = cloud_tts.is_cloud(name) or azure_tts.is_azure(name)   # not AI Studio models: no "exists for your key" check
        google = None if via_cloud else verified["models"].get(name)
        learned = seen.get(name)
        items.append({
            "model": name, "provider": "azure" if azure_tts.is_azure(name) else ("cloud" if via_cloud else "ai_studio"), "per_minute": rpm, "per_day": rpd, "used_today": tts_pool.used_today(name),
            "remaining": tts_pool.remaining(name), "blocked_seconds": round(gemini_tts.blocked_for(name)),
            # 1. exists for this API key? (None = could not check)
            "google": None if (verified["error"] or via_cloud) else ({"exists": True, **google} if google else {"exists": False}),
            # 2. limit stated in Google's own 429 error text the last time this model was refused
            "seen_limit": {"per_day": learned.get("per_day"), "per_minute": learned.get("per_minute"), "metric": learned.get("metric"),
                           "seen_at": _iso(datetime.fromtimestamp(learned["seen_at"], timezone.utc)) if learned.get("seen_at") else None} if learned else None,
            # 3. real limits and usage from Google Cloud (None when not set up)
            "cloud": cloud["models"].get(name) if cloud["configured"] else None})
    return {"models": items, "all_blocked": tts_pool.all_blocked(), "day": tts_pool._today(),
            "verify_error": verified["error"],
            "cloud": {"configured": cloud["configured"], "project": cloud["project"], "error": cloud["error"],
                      "limits_ok": cloud["limits_ok"], "usage_ok": cloud["usage_ok"]}}


@router.get("/google-quota")
def google_quota_raw(refresh: bool = False):
    """Everything Google Cloud returned about the Gemini API quotas (unmatched), to check the model matching by eye."""
    from . import google_quota
    return google_quota.raw(refresh)


# ---------- runtime settings ----------

def _settings_view() -> dict:
    return {**runtime_settings.view(),
            # read-only: set in backend/.env
            "allow_signup": ALLOW_SIGNUP, "default_daily_minutes": DEFAULT_DAILY_MINUTES, "max_video_minutes": MAX_VIDEO_MINUTES,
            "max_upload_mb": MAX_UPLOAD_MB, "max_active_jobs_per_user": MAX_ACTIVE_JOBS_PER_USER, "queue_mode": QUEUE_MODE,
            "prices": usage_log.prices()}


@router.get("/costs")
def costs():
    """Real cost from token counts: per model (last 30 days), per recent video, the measured THB per video minute, and the price table."""
    since = utcnow() - timedelta(days=30)
    table, rate = usage_log.prices(), runtime_settings.usd_thb()
    per_model: dict[str, dict] = {}
    recent = []
    with Session() as s:
        rows = s.execute(select(Job.id, Job.status, Job.charged_seconds, Job.created_at, Job.params, Job.data)
                         .where(Job.created_at >= since).order_by(Job.created_at.desc())).all()
        measured = capacity.measured_cost_per_minute(s)
    for jid, status, charged, created, params, data in rows:
        u = (data or {}).get("usage")
        if not u:
            continue
        for model, v in u.items():
            m = per_model.setdefault(model, {"model": model, "calls": 0, "in": 0, "audio_in": 0, "out": 0, "audio_out": 0, "chars": 0, "est": 0})
            for k in ("calls", "in", "audio_in", "out", "audio_out", "chars", "est"):
                m[k] += v.get(k, 0)
        if len(recent) < 20:
            c = usage_log.cost_thb(u, table, rate)
            recent.append({"id": jid, "created_at": _iso(created), "status": status, "minutes": round((charged or 0) / 60, 1),
                           "edit": bool((params or {}).get("edit")), "cost_thb": round(c["thb"], 2), "complete": c["complete"],
                           "estimated": c["estimated"], "unpriced": c["unpriced"]})
    models = []
    for model, m in sorted(per_model.items(), key=lambda kv: -kv[1]["calls"]):
        c = usage_log.cost_thb({model: m}, table, rate)
        models.append({**m, "thb": round(c["thb"], 2), "priced": c["complete"]})
    for model in table:   # models with a price but no usage yet are still editable
        if model not in per_model:
            models.append({"model": model, "calls": 0, "in": 0, "audio_in": 0, "out": 0, "audio_out": 0, "chars": 0, "est": 0, "thb": 0.0, "priced": True})
    return {"usd_thb": rate, "prices": table, "assumed": sorted(usage_log.ASSUMED), "models": models, "recent": recent,
            "measured_cost_per_minute": round(measured, 3) if measured else None,
            "configured_cost_per_minute": runtime_settings.cost_per_minute_thb(), "total_thb_30d": round(sum(m["thb"] for m in models), 2)}


@router.get("/settings")
def get_settings():
    return _settings_view()


class SettingsPatch(BaseModel):
    maintenance: bool | None = None
    global_daily_minutes: float | None = Field(None, ge=0, le=10_000_000)   # 0 = unlimited
    budget_enabled: bool | None = None
    budget_thb: float | None = Field(None, ge=0, le=100_000_000)             # what is left in the Google billing account
    cost_per_minute_thb: float | None = Field(None, gt=0, le=10_000)
    min_free_minutes: float | None = Field(None, ge=0, le=1_000_000)
    usd_thb: float | None = Field(None, gt=0, le=10_000)
    prices: dict[str, dict[str, float]] | None = None   # {model: {"in","audio_in","out","audio_out"}} USD per 1M tokens


def _check_prices(prices: dict):
    for model, p in prices.items():
        if not model or len(model) > 100 or set(p) - {"in", "audio_in", "out", "audio_out", "chars"} or any(v < 0 or v > 1000 for v in p.values()):
            raise HTTPException(status_code=400, detail="Prices must be USD per 1M tokens between 0 and 1000.")


@router.put("/settings")
def put_settings(body: SettingsPatch, admin: User = Depends(require_admin)):
    before = _settings_view()
    wanted = {k: v for k, v in body.model_dump().items() if v is not None}
    if "prices" in wanted:
        _check_prices(wanted["prices"])
        wanted["prices"] = {**usage_log.prices(), **wanted["prices"]}   # edits are merged into the table
    if wanted:
        runtime_settings.update(**wanted)
    changes = {k: {"from": before[k], "to": v} for k, v in wanted.items() if v != before[k]}
    if changes:
        with Session() as s:
            _audit(s, admin, "settings.update", "settings", "runtime", None, changes)
            s.commit()
    return _settings_view()


# ---------- audit log ----------

@router.get("/audit")
def list_audit(action: str = "", admin_id: int | None = None, page: int = 1, per_page: int = 25):
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    if action and action not in AUDIT_ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown action.")
    with Session() as s:
        query, count = select(AuditLog), select(func.count()).select_from(AuditLog)
        if action:
            query, count = query.where(AuditLog.action == action), count.where(AuditLog.action == action)
        if admin_id is not None:
            query, count = query.where(AuditLog.admin_id == admin_id), count.where(AuditLog.admin_id == admin_id)
        total = s.execute(count).scalar_one()
        rows = s.execute(query.order_by(AuditLog.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return {"total": total, "page": page, "per_page": per_page, "actions": list(AUDIT_ACTIONS),
            "items": [{"id": r.id, "created_at": _iso(r.created_at), "admin_id": r.admin_id, "admin_email": r.admin_email,
                       "action": r.action, "target_type": r.target_type, "target_id": r.target_id,
                       "target_label": r.target_label, "details": r.details or {}} for r in rows]}
