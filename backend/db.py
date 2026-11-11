"""Users and jobs (SQLite by default; set DATABASE_URL=postgresql+psycopg://... for production)."""
import time
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, create_engine, func, inspect, select, text
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
    is_active = Column(Boolean, default=True, nullable=False)   # always == (status == "active"): kept for older code
    status = Column(String(16), default="active", nullable=False)   # active | paused | deactivated | banned
    status_reason = Column(String(300))                              # shown to the owner only
    credit_seconds = Column(Float, default=0.0, nullable=False)     # BOUGHT video seconds (top-ups): used only after the daily / monthly allowance is used up
    device_limit = Column(Integer, default=0, nullable=False)       # how many different devices may use the login; 0 = any number
    created_at = Column(DateTime(timezone=True), default=utcnow)


STATUSES = ("active", "paused", "deactivated", "banned")


def set_status(user: "User", status: str, reason: str | None = None):
    user.status = status
    user.is_active = status == "active"
    user.status_reason = (reason or "").strip()[:300] or None


class UserDevice(Base):
    """A browser/phone that signed in with a login. With device_limit = N, a login can have at most N of these; only the admin frees a slot."""
    __tablename__ = "user_devices"
    __table_args__ = (UniqueConstraint("user_id", "device_id", name="uq_user_device"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    device_id = Column(String(64), nullable=False)      # random id the browser keeps in localStorage ("unknown" when a client sends none)
    name = Column(String(120))                          # e.g. "Chrome on Windows" (from the User-Agent: a website cannot read a real device name)
    browser = Column(String(40))
    os = Column(String(40))
    ip = Column(String(64))                             # last IP
    first_ip = Column(String(64))
    first_seen = Column(DateTime(timezone=True), default=utcnow)
    last_seen = Column(DateTime(timezone=True), default=utcnow)


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
    credit_seconds = Column(Float, default=0.0)    # the part of this video paid with the user's bought minutes; refunded on failure
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


class TopupRequest(Base):
    """A user asks for bought minutes and sends the payment slip; the admin checks the slip and approves (the minutes are added) or rejects."""
    __tablename__ = "topup_requests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    minutes = Column(Integer, nullable=False)
    price_per_minute = Column(Float, nullable=False)   # the price when the request was made (a later price change does not touch it)
    amount_thb = Column(Float, nullable=False)
    status = Column(String(12), default="pending", index=True, nullable=False)   # pending | approved | rejected
    slip_file = Column(String(200))                    # file name inside DATA_DIR/slips
    note = Column(String(300))                         # from the user
    admin_note = Column(String(300))                   # rejection reason
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    decided_at = Column(DateTime(timezone=True))
    decided_by = Column(String(255))


Base.metadata.create_all(engine)

# Small migration for databases created before the monthly allowance existed (create_all never alters tables).
if "monthly_minutes" not in {c["name"] for c in inspect(engine).get_columns("users")}:
    with engine.begin() as _conn:
        _conn.execute(text(f"ALTER TABLE users ADD COLUMN monthly_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_MONTHLY_MINUTES)}"))

_user_cols = {c["name"] for c in inspect(engine).get_columns("users")}
for _col, _ddl in (("status", "status VARCHAR(16) NOT NULL DEFAULT 'active'"), ("status_reason", "status_reason VARCHAR(300)"),
                   ("device_limit", "device_limit INTEGER NOT NULL DEFAULT 0")):
    if _col not in _user_cols:
        with engine.begin() as _conn:
            _conn.execute(text(f"ALTER TABLE users ADD COLUMN {_ddl}"))
            if _col == "status":   # accounts disabled before statuses existed become "deactivated"
                _conn.execute(text("UPDATE users SET status = 'deactivated' WHERE is_active = 0 OR is_active = false" if not DATABASE_URL.startswith("sqlite")
                                   else "UPDATE users SET status = 'deactivated' WHERE is_active = 0"))

if "credit_seconds" not in {c["name"] for c in inspect(engine).get_columns("users")}:
    with engine.begin() as _conn:
        _conn.execute(text("ALTER TABLE users ADD COLUMN credit_seconds FLOAT NOT NULL DEFAULT 0"))
if "credit_seconds" not in {c["name"] for c in inspect(engine).get_columns("jobs")}:
    with engine.begin() as _conn:
        _conn.execute(text("ALTER TABLE jobs ADD COLUMN credit_seconds FLOAT DEFAULT 0"))

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
        prev_stage, prev_progress = job.stage, job.progress
        for k, v in fields.items():
            if k in _COLUMNS:
                setattr(job, k, (v[:2000] if k == "error" and isinstance(v, str) else v))
            else:
                extra[k] = v
        data = dict(job.data or {})
        now = utcnow().isoformat(timespec="seconds")
        if fields.get("stage") and fields["stage"] != prev_stage:   # what the video was doing and when: shows where a failure happened
            data["stages"] = (data.get("stages") or [])[-59:] + [{"stage": fields["stage"], "progress": fields.get("progress", job.progress), "at": now}]
        if fields.get("status") == "error":
            data["failed_stage"] = {"stage": prev_stage, "progress": prev_progress, "at": now}
        try:   # the video's console log (joblog.py): saved at most every 5 s, always when the video ends
            import joblog
            ended = fields.get("status") in ("done", "error", "cancelled")
            lines = joblog.pending(job_id, force=ended)
            if lines is not None:
                data["log"] = lines
        except Exception:
            pass
        if extra or "stages" in data or "failed_stage" in data or "log" in data:
            job.data = {**data, **extra}
        if fields.get("status") in ("done", "error", "cancelled"):
            job.finished_at = utcnow()
        if fields.get("status") in ("error", "cancelled"):
            job.charged_seconds = 0.0  # failed or cancelled jobs don't use up the allowance
            refund_credit(s, job)
        s.commit()
        return True


def save_log(job_id: str) -> None:
    """Save the video's console log now (called when a video ends, after its last lines were printed)."""
    import joblog
    lines = joblog.pending(job_id, force=True)
    if lines is not None:
        with Session() as s:
            job = s.get(Job, job_id)
            if job is not None:
                job.data = {**(job.data or {}), "log": lines}
                s.commit()
    joblog.forget(job_id)


def refund_credit(s, job: "Job") -> None:
    """Give a failed / cancelled video's bought minutes back to the user (once: the job's credit is zeroed)."""
    if job.credit_seconds:
        user = s.get(User, job.user_id)
        if user is not None:
            user.credit_seconds = (user.credit_seconds or 0.0) + job.credit_seconds
        job.credit_seconds = 0.0


def add_usage(job_id: str, usage: dict) -> None:
    """Save a job's token totals (usage.py) in Job.data["usage"]. Works for cancelled jobs too (their tokens were still paid)."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is not None:
            job.data = {**(job.data or {}), "usage": usage}
            s.commit()


def used_seconds_today(s, user_id: int | None = None, with_credit: bool = False) -> float:
    """Allowance seconds used today. with_credit also counts bought minutes (for the global ceiling, which protects the API bill)."""
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.coalesce(func.sum(Job.charged_seconds + (func.coalesce(Job.credit_seconds, 0.0) if with_credit else 0.0)), 0.0)).where(Job.created_at >= start)
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
