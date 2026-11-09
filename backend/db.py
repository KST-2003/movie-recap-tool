"""Users and jobs (SQLite by default; set DATABASE_URL=postgresql+psycopg://... for production)."""
import time
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, create_engine, func, inspect, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL, DEFAULT_DAILY_MINUTES, DEFAULT_MONTHLY_MINUTES

_kwargs = {"connect_args": {"check_same_thread": False, "timeout": 30}} if DATABASE_URL.startswith("sqlite") else {"pool_pre_ping": True, "pool_size": 10}
engine = create_engine(DATABASE_URL, **_kwargs)
Session = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    daily_minutes = Column(Integer, default=DEFAULT_DAILY_MINUTES, nullable=False)
    monthly_minutes = Column(Integer, default=DEFAULT_MONTHLY_MINUTES, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    status = Column(String(16), default="queued", index=True)   # queued | running | done | error | cancelled
    stage = Column(String(120), default="Queued")
    progress = Column(Integer, default=0)
    error = Column(String(2000))
    params = Column(JSON, default=dict)
    data = Column(JSON, default=dict)          # result + misc fields reported to the client
    input_key = Column(String(500))            # storage key of the uploaded video
    logo_key = Column(String(500))
    charged_seconds = Column(Float, default=0.0)   # counted against the user's daily allowance; refunded on failure
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at = Column(DateTime(timezone=True))


class AuditLog(Base):
    """Who changed what in the admin dashboard (written by admin.py in the same transaction as the change)."""
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    admin_id = Column(Integer, index=True)
    admin_email = Column(String(255))      # copied, so the entry stays readable if the account changes
    action = Column(String(40), index=True)   # user.create | user.update | job.cancel | settings.update
    target_type = Column(String(20))       # user | job | settings
    target_id = Column(String(64))
    target_label = Column(String(255))     # e.g. the user's email
    details = Column(JSON, default=dict)   # {field: {"from": old, "to": new}} or small facts; never passwords


Base.metadata.create_all(engine)

# Small migration for databases created before the monthly allowance existed (create_all never alters tables).
if "monthly_minutes" not in {c["name"] for c in inspect(engine).get_columns("users")}:
    with engine.begin() as _conn:
        _conn.execute(text(f"ALTER TABLE users ADD COLUMN monthly_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_MONTHLY_MINUTES)}"))

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


def active_jobs(s, user_id: int) -> int:
    return int(s.execute(select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.status.in_(("queued", "running")))).scalar_one())
