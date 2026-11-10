"""Quota / usage business logic used by api/accounts.py and api/jobs.py: nothing here is FastAPI routing, just
functions that take the data they need and return a dict or raise HTTPException. Split out of main.py so the quota
rules have one home regardless of which route (upload, re-render, /api/usage) needs them."""
import os

from fastapi import HTTPException
from sqlalchemy import func, select

from admin import settings as runtime_settings
from db import Job, Session, active_jobs, used_seconds_month, used_seconds_today

WORKERS = int(os.getenv("QUEUE_WORKERS", os.getenv("RECAP_WORKERS", "2")))  # jobs that run at the same time
DEFAULT_JOB_SECONDS = 300.0
_HIDDEN_FROM_USERS = ("result", "started_at", "run_seconds", "usage", "error_detail")   # internals: cost, raw error text


def quota_view(user) -> dict:
    """What /api/auth/me, /register, /login and /usage all show: today's and this month's allowance and what is left."""
    with Session() as s:
        used = used_seconds_today(s, user.id)
        month_used = used_seconds_month(s, user.id)
    day_left = max(0, user.daily_minutes * 60 - used)
    month_left = max(0, user.monthly_minutes * 60 - month_used)
    return {"daily_minutes": user.daily_minutes, "used_seconds": round(used), "remaining_seconds": round(min(day_left, month_left)),
            "monthly_minutes": user.monthly_minutes, "month_used_seconds": round(month_used),
            "month_remaining_seconds": round(month_left), "day_remaining_seconds": round(day_left)}


def check_limits(s, user, seconds: float, max_active_jobs: int) -> None:
    """Per-user and global limits for a new upload. Must run inside the admission lock, in the same transaction that
    creates the job. `max_active_jobs` is passed in (read from the CALLER's own module globals, i.e. api.jobs.MAX_ACTIVE_JOBS_PER_USER)
    rather than imported here, so a test that monkeypatches that name still controls this check."""
    if active_jobs(s, user.id) >= max_active_jobs:
        raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")
    month_used = used_seconds_month(s, user.id)
    if month_used + seconds > user.monthly_minutes * 60:
        left = max(0, user.monthly_minutes * 60 - month_used)
        raise HTTPException(status_code=402, detail=(
            f"Monthly limit reached: {left / 60:.1f} of your {user.monthly_minutes} minutes left this month, "
            f"this video is {seconds / 60:.1f} minutes."))
    used = used_seconds_today(s, user.id)
    if used + seconds > user.daily_minutes * 60:
        left = max(0, user.daily_minutes * 60 - used)
        raise HTTPException(status_code=402, detail=(
            f"Daily limit reached: {left / 60:.1f} of your {user.daily_minutes} minutes left today, "
            f"this video is {seconds / 60:.1f} minutes."))
    cap = runtime_settings.global_daily_minutes()
    if cap and used_seconds_today(s) + seconds > cap * 60:
        raise HTTPException(status_code=503, detail="We've reached today's capacity. Please try again tomorrow.")


def refuse_if_voice_limit(tts_provider_fn) -> None:
    """Don't accept work (and spend minutes + other quotas) while Gemini's daily voice limit is used up.
    Takes the tts_provider() function as a parameter to avoid importing common.py's mutable provider logic here."""
    if tts_provider_fn() == "gemini":
        import tts_pool
        if tts_pool.all_blocked():
            raise HTTPException(status_code=503, detail=tts_pool.blocked_message())


def queue_info(job) -> dict:
    """Place in line and a rough wait for a queued job: average run time of recent jobs / parallel workers."""
    with Session() as s:
        ahead = s.execute(select(func.count()).select_from(Job).where(
            Job.status == "queued", Job.created_at < job.created_at)).scalar_one()
        running = s.execute(select(func.count()).select_from(Job).where(Job.status == "running")).scalar_one()
        recent = s.execute(select(Job.data).where(Job.status == "done").order_by(Job.finished_at.desc()).limit(20)).scalars().all()
    runs = [d["run_seconds"] for d in recent if d and d.get("run_seconds")]
    avg = sum(runs) / len(runs) if runs else DEFAULT_JOB_SECONDS
    free = max(WORKERS - running, 0)
    waiting_for = max(ahead - free + 1, 0)
    return {"queue_position": ahead + 1, "eta_seconds": int(waiting_for * avg / WORKERS)}


def file_url(key: str, download: bool, signed_url_seconds: int) -> str:
    import auth
    import storage
    name = os.path.basename(key)
    if storage.BACKEND == "s3":
        return storage.presigned_url(key, name if download else None)
    exp, sig = auth.sign_file(name, signed_url_seconds)
    return f"/api/files/{name}?exp={exp}&sig={sig}" + ("&dl=1" if download else "")


def job_view(job, signed_url_seconds: int, file_ttl_hours: float) -> dict:
    import storage
    view = {"id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "error": job.error, **{k: v for k, v in (job.data or {}).items() if k not in _HIDDEN_FROM_USERS}}
    if job.status == "queued":
        view.update(queue_info(job))
    result = (job.data or {}).get("result")
    if result:
        result = dict(result)
        if result.get("video_file") and storage.output_exists(result["video_file"]):
            result["video_url"] = file_url(result["video_file"], False, signed_url_seconds)
            result["download_url"] = file_url(result["video_file"], True, signed_url_seconds)
            result["subtitle_url"] = file_url(result["subtitle_file"], True, signed_url_seconds)
        else:
            result["expired"] = True  # files are deleted after FILE_TTL_HOURS
        view["result"] = result
    return view


def clean_blurs(raw: str) -> list:
    """Parse the preview's blur boxes; keep at most 6 sane [x, y, w, h] fractions."""
    import json
    try:
        rects = json.loads(raw) if raw else []
        out = []
        for r in rects[:6]:
            x, y, w, h = (min(max(float(v), 0.0), 1.0) for v in r)
            if w > 0.01 and h > 0.01:
                out.append([x, y, min(w, 1 - x), min(h, 1 - y)])
        return out
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid blur boxes.")
