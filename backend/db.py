"""Users and jobs (SQLite by default; set DATABASE_URL=postgresql+psycopg://... for production)."""
import time
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, create_engine, func, select
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL, DEFAULT_DAILY_MINUTES

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
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String(32), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    status = Column(String(16), default="queued", index=True)   # queued | running | done | error
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


Base.metadata.create_all(engine)

_COLUMNS = {"status", "stage", "progress", "error"}


def update_job(job_id: str, **fields):
    """Used by the pipeline; known columns are stored directly, everything else lands in Job.data."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None:
            return
        extra = {}
        for k, v in fields.items():
            if k in _COLUMNS:
                setattr(job, k, v)
            else:
                extra[k] = v
        if extra:
            job.data = {**(job.data or {}), **extra}
        if fields.get("status") in ("done", "error"):
            job.finished_at = utcnow()
        if fields.get("status") == "error":
            job.charged_seconds = 0.0  # failed jobs don't use up the allowance
        s.commit()


def used_seconds_today(s, user_id: int | None = None) -> float:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.coalesce(func.sum(Job.charged_seconds), 0.0)).where(Job.created_at >= start)
    if user_id is not None:
        q = q.where(Job.user_id == user_id)
    return float(s.execute(q).scalar_one())


def active_jobs(s, user_id: int) -> int:
    return int(s.execute(select(func.count()).select_from(Job).where(
        Job.user_id == user_id, Job.status.in_(("queued", "running")))).scalar_one())
