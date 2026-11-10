"""SQLAlchemy table definitions and the engine/session (SQLite by default; set DATABASE_URL=postgresql+psycopg://... for production).
Query helpers (used_seconds_today, active_jobs, update_job, ...) live in repository.py, not here -- this file is just the schema.
db.py re-exports everything from this module and from repository.py, so existing `from db import ...` imports are unaffected."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, create_engine, inspect, text
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
    token_version = Column(Integer, default=0, nullable=False)   # bumped to cancel every token issued so far (password reset, disable, promote/demote, log out everywhere)
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


class EditUse(Base):
    """One editor action that can spend voice requests (a live line preview, or a re-render). Counted per user per day and per source
    video so nobody can use up the shared voice quota (see edit_limits.py)."""
    __tablename__ = "edit_use"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    video_id = Column(String(32), index=True, nullable=False)   # the ORIGINAL job id (re-renders point back to it)
    kind = Column(String(12), nullable=False)                    # preview | rerender
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)


Base.metadata.create_all(engine)

# Small migrations for databases created before these columns existed (create_all never alters tables).
if "monthly_minutes" not in {c["name"] for c in inspect(engine).get_columns("users")}:
    with engine.begin() as _conn:
        _conn.execute(text(f"ALTER TABLE users ADD COLUMN monthly_minutes INTEGER NOT NULL DEFAULT {int(DEFAULT_MONTHLY_MINUTES)}"))

if "token_version" not in {c["name"] for c in inspect(engine).get_columns("users")}:
    with engine.begin() as _conn:
        _conn.execute(text("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
