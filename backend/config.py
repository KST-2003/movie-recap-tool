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
DEFAULT_DAILY_MINUTES = int(os.getenv("DEFAULT_DAILY_MINUTES", "100"))   # per user, per UTC day
DEFAULT_MONTHLY_MINUTES = int(os.getenv("DEFAULT_MONTHLY_MINUTES", "2000"))   # per user, per UTC calendar month
# Self-service sign-ups get a small TRIAL allowance (an admin raises it in the dashboard); accounts made by an admin / manage.py get the defaults above.
SIGNUP_DAILY_MINUTES = int(os.getenv("SIGNUP_DAILY_MINUTES", "10"))
SIGNUP_MONTHLY_MINUTES = int(os.getenv("SIGNUP_MONTHLY_MINUTES", "30"))
SIGNUP_MAX_PER_DAY = int(os.getenv("SIGNUP_MAX_PER_DAY", "100"))   # new accounts per UTC day, all addresses together (0 = no cap): a circuit breaker
MAX_VIDEO_MINUTES = float(os.getenv("MAX_VIDEO_MINUTES", "15"))         # per single upload
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "1024"))
MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "2"))
GLOBAL_DAILY_MINUTES = float(os.getenv("GLOBAL_DAILY_MINUTES", "0"))    # 0 = unlimited; protects the API bill
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "").lower() in ("1", "true")  # kill switch for new jobs
# OFF by default: FastAPI's interactive docs (/docs, /redoc) and /openapi.json need no login and hand out a full map of
# every route, including every admin one (route names only, never data, but still unnecessary attack-surface mapping
# for a production API nobody browses by hand). Turn on locally with API_DOCS=true if you want to click through them.
API_DOCS = os.getenv("API_DOCS", "").lower() in ("1", "true")

CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001").split(",") if o.strip()]
# Browser sessions live in an httpOnly cookie (see auth.py). The user app and the admin app share the API host, so the server also checks WHICH app a request
# comes from: admin sessions are only accepted from ADMIN_ORIGINS (the browser sets Origin; page scripts cannot forge it).
ADMIN_ORIGINS = [o.strip() for o in os.getenv("ADMIN_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001").split(",") if o.strip()]
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "strict").lower()   # strict | lax. The apps and the API must share one registrable domain (app.x.com, admin.x.com, api.x.com)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "auto").lower()         # auto = Secure when the request came in over HTTPS (also behind a trusted proxy) | 1 | 0
FILE_TTL_HOURS = float(os.getenv("FILE_TTL_HOURS", "24"))
SIGNED_URL_SECONDS = int(os.getenv("SIGNED_URL_SECONDS", "3600"))
