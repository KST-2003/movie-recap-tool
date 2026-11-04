"""Shared settings (read from the environment / backend/.env)."""
import os

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "data")
UPLOAD_DIR = os.path.join(os.getenv("UPLOAD_DIR", "uploads"))
LOGOS_DIR = os.path.join(UPLOAD_DIR, "logos")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "outputs")
for _d in (DATA_DIR, UPLOAD_DIR, LOGOS_DIR, OUTPUT_DIR):
    os.makedirs(_d, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/app.db")
REDIS_URL = os.getenv("REDIS_URL", "")
QUEUE_MODE = os.getenv("QUEUE_MODE", "rq" if REDIS_URL else "inline")  # inline = in-process threads (dev)

# Accounts and limits
ALLOW_SIGNUP = os.getenv("ALLOW_SIGNUP", "true").lower() == "true"
DEFAULT_DAILY_MINUTES = int(os.getenv("DEFAULT_DAILY_MINUTES", "20"))   # per user, per UTC day
MAX_VIDEO_MINUTES = float(os.getenv("MAX_VIDEO_MINUTES", "15"))         # per single upload
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))
MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "2"))
GLOBAL_DAILY_MINUTES = float(os.getenv("GLOBAL_DAILY_MINUTES", "0"))    # 0 = unlimited; protects the API bill
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "").lower() in ("1", "true")  # kill switch for new jobs

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o.strip()]
FILE_TTL_HOURS = float(os.getenv("FILE_TTL_HOURS", "24"))
SIGNED_URL_SECONDS = int(os.getenv("SIGNED_URL_SECONDS", "3600"))
