"""Compatibility façade: the table definitions moved to models.py and the query/write helpers to repository.py
(see each file's own docstring). Kept so every existing `from db import Job, Session, update_job, ...` elsewhere in
the codebase, and in every test file, keeps working completely unchanged."""
from models import AuditLog, Base, EditUse, Job, Session, User, engine, utcnow
from repository import (
    ADMISSION_LOCK_ID, active_jobs, add_usage, lock_admission, month_start, update_job, used_seconds_month, used_seconds_today,
)

__all__ = [
    "AuditLog", "Base", "EditUse", "Job", "Session", "User", "engine", "utcnow",
    "ADMISSION_LOCK_ID", "active_jobs", "add_usage", "lock_admission", "month_start", "update_job", "used_seconds_month", "used_seconds_today",
]
