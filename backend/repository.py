"""Query and write helpers for the Job/User tables: everything that is more than a bare SQLAlchemy model. The table
definitions themselves live in models.py; db.py re-exports both so existing `from db import ...` imports are unaffected."""
from sqlalchemy import func, select, text

from models import Job, Session, engine, utcnow

_COLUMNS = {"status", "stage", "progress", "error"}


def update_job(job_id: str, **fields) -> bool:
    """Used by the pipeline; known columns are stored directly, everything else lands in Job.data.
    Returns False (and changes nothing) when the job was cancelled by the user in the meantime."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None:
            return False
        if job.status == "cancelled" and fields.get("status") != "cancelled":
            return False
        extra = {}
        for k, v in fields.items():
            if k in _COLUMNS:
                setattr(job, k, v)
            else:
                extra[k] = v
        if extra:
            job.data = {**(job.data or {}), **extra}
        if fields.get("status") in ("done", "error", "cancelled"):
            job.finished_at = utcnow()
        if fields.get("status") in ("error", "cancelled"):
            job.charged_seconds = 0.0  # failed or cancelled jobs don't use up the allowance
        s.commit()
        return True


def add_usage(job_id: str, usage: dict) -> None:
    """Save a job's token totals (usage.py) in Job.data["usage"]. Works for cancelled jobs too (their tokens were still paid)."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is not None:
            job.data = {**(job.data or {}), "usage": usage}
            s.commit()


def used_seconds_today(s, user_id: int | None = None) -> float:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.coalesce(func.sum(Job.charged_seconds), 0.0)).where(Job.created_at >= start)
    if user_id is not None:
        q = q.where(Job.user_id == user_id)
    return float(s.execute(q).scalar_one())


def month_start():
    return utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def used_seconds_month(s, user_id: int | None = None) -> float:
    q = select(func.coalesce(func.sum(Job.charged_seconds), 0.0)).where(Job.created_at >= month_start())
    if user_id is not None:
        q = q.where(Job.user_id == user_id)
    return float(s.execute(q).scalar_one())


ADMISSION_LOCK_ID = 727001


def lock_admission(s) -> None:
    """Serialise 'check the limits, then create the job' across ALL API processes (released at commit/rollback).
    Postgres: advisory lock. SQLite (dev, one process): the caller also holds capacity.lock, and the write lock covers the rest."""
    if engine.dialect.name == "postgresql":
        s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ADMISSION_LOCK_ID})


def active_jobs(s, user_id: int) -> int:
    return int(s.execute(select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.status.in_(("queued", "running")))).scalar_one())
