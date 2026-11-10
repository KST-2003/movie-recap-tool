"""Admin API for the dashboard (/api/admin/*). Every route needs a logged-in user with is_admin = True
(make one with `python manage.py create-user EMAIL PASSWORD --admin`)."""
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select

import auth
from config import (ALLOW_SIGNUP, DEFAULT_DAILY_MINUTES, DEFAULT_MONTHLY_MINUTES, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES,
                    QUEUE_MODE)
import alerts
import capacity
import usage as usage_log
from . import settings as runtime_settings
import storage
from db import STATUSES as USER_STATUSES, AuditLog, Job, Session, TopupRequest, User, UserDevice, month_start, set_status, update_job, used_seconds_month, used_seconds_today, utcnow

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STATUSES = ("queued", "running", "done", "error", "cancelled")
AUDIT_ACTIONS = ("user.create", "user.update", "user.device", "topup.approve", "topup.reject", "credit.adjust", "job.cancel", "settings.update")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._@+-]{2,63}$")
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/l/I: easy to read out or type from a message


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
        topups_pending = s.execute(select(func.count()).select_from(TopupRequest).where(TopupRequest.status == "pending")).scalar_one()
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
        "topups_pending": topups_pending,
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

def make_password() -> str:
    """A readable one-time password like 'Xk7m-Pq2n-Rt9w' (the admin tells it to the user; it is never stored in plain text)."""
    raw = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def make_username(s) -> str:
    while True:
        name = "user" + "".join(secrets.choice("0123456789") for _ in range(6))
        if not s.execute(select(User.id).where(User.email == name)).first():
            return name


def _device_row(d: UserDevice) -> dict:
    return {"id": d.id, "name": d.name, "browser": d.browser, "os": d.os, "ip": d.ip, "first_ip": d.first_ip,
            "first_seen": _iso(d.first_seen), "last_seen": _iso(d.last_seen)}


def _user_row(u: User, used_seconds: float, month_seconds: float = 0.0, devices: list | None = None) -> dict:
    devices = sorted(devices or [], key=lambda d: d.last_seen or d.first_seen, reverse=True)
    last = devices[0] if devices else None
    return {"id": u.id, "email": u.email, "daily_minutes": u.daily_minutes, "monthly_minutes": u.monthly_minutes,
            "is_admin": u.is_admin, "is_active": u.is_active, "status": u.status, "status_reason": u.status_reason,
            "device_limit": u.device_limit, "device_count": len(devices), "credit_minutes": round(max(0.0, u.credit_seconds or 0.0) / 60, 1),
            "last_seen": _iso(last.last_seen) if last else None, "last_ip": last.ip if last else None,
            "last_device": last.name if last else None, "last_browser": last.browser if last else None, "last_os": last.os if last else None,
            "created_at": _iso(u.created_at), "used_minutes_today": round(used_seconds / 60, 1),
            "used_minutes_month": round(month_seconds / 60, 1)}


@router.get("/users")
def list_users(q: str = "", page: int = 1, per_page: int = 25, status: str = ""):
    per_page = min(max(per_page, 1), 100)
    page = max(page, 1)
    if status and status not in USER_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    today = _day_start()
    with Session() as s:
        query = select(User)
        count = select(func.count()).select_from(User)
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query, count = query.where(User.email.like(like)), count.where(User.email.like(like))
        if status:
            query, count = query.where(User.status == status), count.where(User.status == status)
        total = s.execute(count).scalar_one()
        users = s.execute(query.order_by(User.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
        ids = [u.id for u in users]
        used = dict(s.execute(select(Job.user_id, func.coalesce(func.sum(Job.charged_seconds), 0.0))
                              .where(Job.created_at >= today, Job.user_id.in_(ids))
                              .group_by(Job.user_id)).all()) if users else {}
        month_used = dict(s.execute(select(Job.user_id, func.coalesce(func.sum(Job.charged_seconds), 0.0))
                                    .where(Job.created_at >= month_start(), Job.user_id.in_(ids))
                                    .group_by(Job.user_id)).all()) if users else {}
        devices: dict[int, list] = {}
        for d in (s.execute(select(UserDevice).where(UserDevice.user_id.in_(ids))).scalars().all() if users else []):
            devices.setdefault(d.user_id, []).append(d)
    return {"total": total, "page": page, "per_page": per_page,
            "items": [_user_row(u, float(used.get(u.id, 0.0)), float(month_used.get(u.id, 0.0)), devices.get(u.id)) for u in users],
            "default_daily_minutes": DEFAULT_DAILY_MINUTES, "default_monthly_minutes": DEFAULT_MONTHLY_MINUTES, "statuses": list(USER_STATUSES)}


class NewUser(BaseModel):
    username: str | None = None          # empty = generated (user123456)
    email: str | None = None             # older name of the same field
    password: str | None = None          # empty = generated
    daily_minutes: int = Field(DEFAULT_DAILY_MINUTES, ge=0, le=100000)
    monthly_minutes: int = Field(DEFAULT_MONTHLY_MINUTES, ge=0, le=3000000)
    is_admin: bool = False
    device_limit: int = Field(1, ge=0, le=20)   # 1 = one device only, 0 = any number of devices (the admin chooses per account)


@router.post("/users")
def create_user(body: NewUser, admin: User = Depends(require_admin)):
    password = body.password or make_password()
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with Session() as s:
        name = (body.username or body.email or "").strip().lower() or make_username(s)
        if not USERNAME_RE.match(name):
            raise HTTPException(status_code=400, detail="Username: 3-64 characters, letters, numbers and . _ - @ + only.")
        if s.execute(select(User).where(User.email == name)).scalar_one_or_none():
            raise HTTPException(status_code=409, detail="That username is already taken.")
        user = User(email=name, password_hash=auth.hash_password(password), daily_minutes=body.daily_minutes, monthly_minutes=body.monthly_minutes,
                    is_admin=body.is_admin, device_limit=body.device_limit)
        s.add(user)
        s.flush()
        _audit(s, admin, "user.create", "user", user.id, user.email, {"daily_minutes": user.daily_minutes, "monthly_minutes": user.monthly_minutes,
                                                                      "is_admin": user.is_admin, "device_limit": user.device_limit})
        s.commit()
        return {**_user_row(user, 0.0), "password": password}   # the only time the password can be seen: only its hash is stored


class UserPatch(BaseModel):
    daily_minutes: int | None = Field(None, ge=0, le=100000)
    monthly_minutes: int | None = Field(None, ge=0, le=3000000)
    is_active: bool | None = None            # older switch: false = deactivated
    status: str | None = None                # active | paused | deactivated | banned
    status_reason: str | None = Field(None, max_length=300)
    device_limit: int | None = Field(None, ge=0, le=20)
    is_admin: bool | None = None
    password: str | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin)):
    new_status = body.status or (None if body.is_active is None else ("active" if body.is_active else "deactivated"))
    if new_status is not None and new_status not in USER_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    if user_id == admin.id and (new_status not in (None, "active") or body.is_admin is False):
        raise HTTPException(status_code=400, detail="You cannot disable or demote your own account.")
    if body.password is not None and len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    cancel = []
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        changes = {}
        for field in ("daily_minutes", "monthly_minutes", "is_admin", "device_limit"):
            new = getattr(body, field)
            if new is not None and new != getattr(user, field):
                changes[field] = {"from": getattr(user, field), "to": new}
                setattr(user, field, new)
        if new_status is not None:
            reason = body.status_reason if body.status_reason is not None else (user.status_reason if new_status != "active" else None)
            if new_status != user.status:
                changes["status"] = {"from": user.status, "to": new_status}
            if (reason or "").strip() != (user.status_reason or ""):
                changes["status_reason"] = {"from": user.status_reason, "to": (reason or "").strip() or None}
            set_status(user, new_status, reason)
            if new_status == "banned":   # a banned user's videos stop too
                cancel = [j.id for j in s.execute(select(Job).where(Job.user_id == user.id, Job.status.in_(("queued", "running")))).scalars().all()]
        if body.password is not None:
            user.password_hash = auth.hash_password(body.password)
            changes["password_reset"] = True   # the password itself is never stored in the log
        if changes:
            _audit(s, admin, "user.update", "user", user.id, user.email, changes)
        s.commit()
        devices = s.execute(select(UserDevice).where(UserDevice.user_id == user.id)).scalars().all()
        row = _user_row(user, used_seconds_today(s, user.id), used_seconds_month(s, user.id), devices)
    for jid in cancel:
        update_job(jid, status="cancelled", stage="Cancelled by admin")
    return row


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, admin: User = Depends(require_admin)):
    """Make a new password for the user. Only the admin can do this; every old session of the user stops working."""
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        password = make_password()
        user.password_hash = auth.hash_password(password)
        _audit(s, admin, "user.update", "user", user.id, user.email, {"password_reset": True})
        s.commit()
    return {"username": user.email, "password": password}


@router.get("/users/{user_id}/devices")
def user_devices(user_id: int):
    with Session() as s:
        if s.get(User, user_id) is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        rows = s.execute(select(UserDevice).where(UserDevice.user_id == user_id).order_by(UserDevice.last_seen.desc())).scalars().all()
    return {"items": [_device_row(d) for d in rows]}


@router.delete("/users/{user_id}/devices/{device_pk}")
def remove_device(user_id: int, device_pk: int, admin: User = Depends(require_admin)):
    """Free a slot: that device is signed out and the next device to log in takes its place."""
    with Session() as s:
        user, d = s.get(User, user_id), s.get(UserDevice, device_pk)
        if user is None or d is None or d.user_id != user_id:
            raise HTTPException(status_code=404, detail="Unknown device")
        _audit(s, admin, "user.device", "user", user.id, user.email, {"removed": d.name, "ip": d.ip})
        s.delete(d)
        s.commit()
    return {"removed": True}


@router.delete("/users/{user_id}/devices")
def remove_all_devices(user_id: int, admin: User = Depends(require_admin)):
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        rows = s.execute(select(UserDevice).where(UserDevice.user_id == user_id)).scalars().all()
        for d in rows:
            s.delete(d)
        _audit(s, admin, "user.device", "user", user.id, user.email, {"removed": f"all ({len(rows)})"})
        s.commit()
    return {"removed": len(rows)}


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
                      "video_minutes": round(((job.charged_seconds or 0) + (job.credit_seconds or 0)) / 60, 1), "run_seconds": data.get("run_seconds"),
                      "created_at": _iso(job.created_at), "finished_at": _iso(job.finished_at)})
    return {"total": total, "page": page, "per_page": per_page, "items": items}


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    """Everything about one video for the owner: the full error, where it failed, the stage history and EVERY option the user chose."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        owner = s.get(User, job.user_id)
        params, data = dict(job.params or {}), dict(job.data or {})
        result = dict(data.get("result") or {})
        project = result.pop("project", None)
        result.pop("transcript", None)
        result.pop("timeline", None)
        for k in ("video_file", "subtitle_file"):
            result.pop(k, None)
        table, rate = usage_log.prices(), runtime_settings.usd_thb()
        cost = usage_log.cost_thb(data.get("usage"), table, rate) if data.get("usage") else None
        return {
            "id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "user": {"id": job.user_id, "email": owner.email if owner else None, "status": getattr(owner, "status", None)},
            "error": job.error, "error_detail": data.get("error_detail"), "failed_stage": data.get("failed_stage"), "stages": data.get("stages") or [],
            "params": params,
            "charged_minutes": round((job.charged_seconds or 0) / 60, 2), "bought_minutes": round((job.credit_seconds or 0) / 60, 2),
            "run_seconds": data.get("run_seconds"), "created_at": _iso(job.created_at), "finished_at": _iso(job.finished_at),
            "cost_thb": round(cost["thb"], 2) if cost else None, "cost_complete": cost["complete"] if cost else None, "usage": data.get("usage"),
            "result": result or None, "result_lines": len(project["lines"]) if isinstance(project, dict) and isinstance(project.get("lines"), list) else None,
            "source_kept": storage.source_exists(job.input_key), "has_logo": bool(job.logo_key),
        }


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
            "prices": usage_log.prices(), "storage": storage.disk_usage() if storage.BACKEND == "local" else None}


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
    cost_per_minute_standard_thb: float | None = Field(None, gt=0, le=10_000)   # Standard (Azure) voice videos
    min_free_minutes: float | None = Field(None, ge=0, le=1_000_000)
    usd_thb: float | None = Field(None, gt=0, le=10_000)
    price_per_minute_thb: float | None = Field(None, gt=0, le=10_000)   # what the user pays for one video minute
    topup_packs: list[int] | None = Field(None, min_length=1, max_length=8)   # pack sizes in minutes
    payment_note: str | None = Field(None, max_length=500)           # shown next to the QR (account name, what to write on the slip...)
    keep_result_days: float | None = Field(None, ge=1, le=3650)   # how long finished videos are kept
    keep_source_days: float | None = Field(None, ge=1, le=3650)   # how long uploaded sources / voice clips are kept (editing needs them)
    video_crf: int | None = Field(None, ge=16, le=30)   # x264 quality of new renders (lower = sharper, bigger, slower)
    prices: dict[str, dict[str, float]] | None = None   # {model: {"in","audio_in","out","audio_out"}} USD per 1M tokens


def _check_prices(prices: dict):
    for model, p in prices.items():
        if not model or len(model) > 100 or set(p) - {"in", "audio_in", "out", "audio_out", "chars"} or any(v < 0 or v > 1000 for v in p.values()):
            raise HTTPException(status_code=400, detail="Prices must be USD per 1M tokens between 0 and 1000.")


@router.put("/settings")
def put_settings(body: SettingsPatch, admin: User = Depends(require_admin)):
    before = _settings_view()
    wanted = {k: v for k, v in body.model_dump().items() if v is not None}
    if "topup_packs" in wanted:
        if any(m < 1 or m > 100000 for m in wanted["topup_packs"]):
            raise HTTPException(status_code=400, detail="Pack sizes must be between 1 and 100000 minutes.")
        wanted["topup_packs"] = sorted(set(wanted["topup_packs"]))
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


# ---------- pay as you go: pricing, payment QR, slips, credit ----------

@router.get("/pricing")
def pricing():
    """How the price per minute compares with what a video minute really costs us (measured, else the configured estimate)."""
    import topup
    price = runtime_settings.price_per_minute_thb()
    with Session() as s:
        cost = {q: capacity.measured_cost_per_minute(s, q) or capacity.configured_cost(q) for q in ("premium", "standard")}
        measured = {q: capacity.measured_cost_per_minute(s, q) is not None for q in ("premium", "standard")}
    margin = {q: round((price - c) / price * 100, 1) if price > 0 else None for q, c in cost.items()}
    return {"price_per_minute": price, "packs": topup.packs(), "cost_per_minute": {q: round(c, 2) for q, c in cost.items()}, "cost_measured": measured,
            "margin_percent": margin, "payment_note": runtime_settings.payment_note(), "qr_url": topup.link(runtime_settings.payment_qr_file())}


@router.post("/payment-qr")
def upload_qr(file: UploadFile = File(...), admin: User = Depends(require_admin)):
    import os
    import uuid
    import topup
    from config import DATA_DIR
    data, kind = topup.read_image(file, 3, allow_pdf=False)
    name = f"payment_qr_{uuid.uuid4().hex[:8]}.{kind}"
    with open(os.path.join(DATA_DIR, name), "wb") as f:
        f.write(data)
    old = runtime_settings.payment_qr_file()
    runtime_settings.update(payment_qr_file=name)
    if old and old != name:
        try:
            os.remove(os.path.join(DATA_DIR, old))
        except OSError:
            pass
    with Session() as s:
        _audit(s, admin, "settings.update", "settings", "runtime", None, {"payment_qr": {"from": bool(old), "to": True}})
        s.commit()
    return pricing()


@router.delete("/payment-qr")
def delete_qr(admin: User = Depends(require_admin)):
    import os
    from config import DATA_DIR
    old = runtime_settings.payment_qr_file()
    if old:
        runtime_settings.update(payment_qr_file=None)
        try:
            os.remove(os.path.join(DATA_DIR, old))
        except OSError:
            pass
        with Session() as s:
            _audit(s, admin, "settings.update", "settings", "runtime", None, {"payment_qr": {"from": True, "to": False}})
            s.commit()
    return pricing()


TOPUP_STATUSES = ("pending", "approved", "rejected")


@router.get("/topups")
def list_topups(status: str = "", page: int = 1, per_page: int = 25):
    import topup
    per_page, page = min(max(per_page, 1), 100), max(page, 1)
    if status and status not in TOPUP_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status.")
    with Session() as s:
        q, c = select(TopupRequest, User.email).join(User, User.id == TopupRequest.user_id), select(func.count()).select_from(TopupRequest)
        if status:
            q, c = q.where(TopupRequest.status == status), c.where(TopupRequest.status == status)
        total = s.execute(c).scalar_one()
        rows = s.execute(q.order_by(TopupRequest.id.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return {"total": total, "page": page, "per_page": per_page,
            "items": [{**topup.request_row(r), "user_id": r.user_id, "email": email, "slip_url": topup.link(r.slip_file), "decided_by": r.decided_by,
                       "price_per_minute": r.price_per_minute} for r, email in rows]}


def _decide(topup_id: int, admin: User, approve: bool, reason: str = ""):
    import topup
    with Session() as s:
        row = s.get(TopupRequest, topup_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Unknown top-up.")
        user = s.get(User, row.user_id)
        # only a pending request can be decided, and only once (two admins clicking together cannot add the minutes twice)
        taken = s.execute(TopupRequest.__table__.update().where(TopupRequest.id == topup_id, TopupRequest.status == "pending")
                          .values(status="approved" if approve else "rejected", decided_at=utcnow(), decided_by=admin.email,
                                  admin_note=None if approve else (reason.strip()[:300] or None))).rowcount
        if not taken:
            raise HTTPException(status_code=409, detail="This top-up was already decided.")
        if approve:
            user.credit_seconds = (user.credit_seconds or 0.0) + row.minutes * 60
        _audit(s, admin, "topup.approve" if approve else "topup.reject", "user", user.id, user.email,
               {"minutes": row.minutes, "amount_thb": row.amount_thb, **({} if approve else {"reason": reason.strip()[:300]})})
        s.commit()
        s.refresh(row)
        return {**topup.request_row(row), "email": user.email, "credit_minutes": round(max(0.0, user.credit_seconds or 0.0) / 60, 1)}


@router.post("/topups/{topup_id}/approve")
def approve_topup(topup_id: int, admin: User = Depends(require_admin)):
    return _decide(topup_id, admin, True)


class Reject(BaseModel):
    reason: str = Field("", max_length=300)


@router.post("/topups/{topup_id}/reject")
def reject_topup(topup_id: int, body: Reject, admin: User = Depends(require_admin)):
    return _decide(topup_id, admin, False, body.reason)


class CreditAdjust(BaseModel):
    minutes: float = Field(ge=-1_000_000, le=1_000_000)   # + adds bought minutes, - takes some back (never below 0)
    note: str = Field("", max_length=300)


@router.post("/users/{user_id}/credit")
def adjust_credit(user_id: int, body: CreditAdjust, admin: User = Depends(require_admin)):
    """Top up by hand (for example after a payment you checked outside the slip flow), or correct a balance."""
    if body.minutes == 0:
        raise HTTPException(status_code=400, detail="Enter a number of minutes.")
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Unknown user")
        before = max(0.0, user.credit_seconds or 0.0)
        user.credit_seconds = max(0.0, before + body.minutes * 60)
        _audit(s, admin, "credit.adjust", "user", user.id, user.email, {"minutes": body.minutes, "note": body.note.strip()[:300],
                                                                          "balance": {"from": round(before / 60, 1), "to": round(user.credit_seconds / 60, 1)}})
        s.commit()
        return {"credit_minutes": round(user.credit_seconds / 60, 1)}


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
