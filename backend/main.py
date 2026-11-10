import json
from config import (ALLOW_SIGNUP, API_DOCS, CORS_ORIGINS, DEFAULT_DAILY_MINUTES, FILE_TTL_HOURS, SIGNUP_DAILY_MINUTES, SIGNUP_MAX_PER_DAY, SIGNUP_MONTHLY_MINUTES,
                    LOGOS_DIR, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES,
                    OUTPUT_DIR, SIGNED_URL_SECONDS, UPLOAD_DIR)

import os
import re
import threading
from contextlib import asynccontextmanager
import time
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from datetime import timedelta, timezone

from sqlalchemy import func, select

import auth
from admin import router as admin_router, settings as runtime_settings
import alerts
import capacity
import edit_limits
from guard import RequestGuard
import usage as usage_log   # (main.py has an endpoint function called usage)
import jobs_queue
import ratelimit
import sandbox
import safe_media
import looks
import storage
from common import tts_provider, upload_duration
from db import Job, Session, User, active_jobs, lock_admission, month_start, used_seconds_month, used_seconds_today, utcnow
from voices import VOICES, VOICE_NAMES

import logging


class _QuietPolling(logging.Filter):
    """The page polls /api/jobs/<id> every 1.5 s; those lines bury everything useful in the terminal."""
    def filter(self, record):
        msg = record.getMessage()
        return not ("GET /api/jobs/" in msg and '" 200' in msg)


logging.getLogger("uvicorn.access").addFilter(_QuietPolling())

usage_log.install()
sandbox.harden_process()   # Linux: children (ffmpeg ...) cannot read this process's environment / memory through /proc
@asynccontextmanager
async def lifespan(_app):
    """Start-up work (the old @app.on_event("startup"), deprecated in FastAPI): runs once per server process, before the first request."""
    _fail_orphaned_jobs()
    if storage.BACKEND == "local":
        threading.Thread(target=_cleanup_loop, daemon=True).start()
    yield


app = FastAPI(title="Movie Recap Tool Backend", version="3.0.0", lifespan=lifespan,
             docs_url="/docs" if API_DOCS else None, redoc_url="/redoc" if API_DOCS else None,
             openapi_url="/openapi.json" if API_DOCS else None)
app.add_middleware(RequestGuard)   # BEFORE the CORS middleware: its 401 / 413 answers must still carry the CORS headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in CORS_ORIGINS if o != "*"],   # explicit origins only: browsers refuse "*" together with cookies
    allow_credentials=True,   # the apps' session is an httpOnly cookie
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)

SAMPLES_DIR = "voice_samples"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- housekeeping ----------

def _cleanup_loop():
    while True:
        try:
            removed = storage.cleanup()
            if removed:
                print(f"[cleanup] removed {removed} old file(s)", flush=True)
        except Exception as exc:
            print(f"[cleanup] failed: {exc}", flush=True)
        time.sleep(3600)


def _fail_orphaned_jobs():
    """Jobs run in this process when there is no Redis queue, so a restart kills them. Without this they stay
    'running' forever and count against the user's active-job limit."""
    from config import QUEUE_MODE
    if QUEUE_MODE != "inline":
        return  # with RQ the jobs live in Redis and the workers keep running
    with Session() as s:
        stuck = s.execute(select(Job).where(Job.status.in_(("queued", "running")))).scalars().all()
        for job in stuck:
            job.status, job.stage, job.charged_seconds = "error", "Interrupted", 0.0
            job.error = "The server was restarted while this video was processing. Please upload it again."
        s.commit()
        if stuck:
            print(f"[startup] marked {len(stuck)} interrupted job(s) as failed", flush=True)


@app.get("/")
def read_root():
    return {"message": "Movie Recap Tool API", "version": app.version}


@app.get("/health")
def health():
    return {"ok": True}


# ---------- accounts ----------

class Credentials(BaseModel):
    email: str
    password: str
    audience: str = "app"   # "admin" = the owner dashboard (needs an admin account and the dashboard's origin)
    cookie: bool = False    # True = browser apps: the session goes into an httpOnly cookie and the body carries only a CSRF token; False = the token is in the body


def _session_reply(request: Request, response: Response, user: User, payload: dict, audience: str, cookie: bool) -> dict:
    token = auth.make_token(user, audience=audience)
    if cookie:
        auth.set_session_cookie(response, request, token, audience)
        payload["csrf_token"] = auth.csrf_for(token)
    else:
        payload["token"] = token
    return payload


def _quota(user: User) -> dict:
    with Session() as s:
        used = used_seconds_today(s, user.id)
        month_used = used_seconds_month(s, user.id)
    day_left = max(0, user.daily_minutes * 60 - used)
    month_left = max(0, user.monthly_minutes * 60 - month_used)
    return {"daily_minutes": user.daily_minutes, "used_seconds": round(used), "remaining_seconds": round(min(day_left, month_left)),
            "monthly_minutes": user.monthly_minutes, "month_used_seconds": round(month_used),
            "month_remaining_seconds": round(month_left), "day_remaining_seconds": round(day_left)}


@app.post("/api/auth/register")
def register(body: Credentials, request: Request, response: Response):
    ratelimit.register_attempt(request)
    ratelimit.check_password_length(body.password)
    if body.cookie:
        auth.check_issue_origin(request, "app")
    if not ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="Sign-ups are closed.")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    password_hash = auth.hash_password(body.password)   # slow on purpose: done before taking the lock
    with Session() as s:
        with capacity.lock:   # the daily cap is checked and the account created as one step: a burst cannot exceed it
            lock_admission(s)
            if s.execute(select(User).where(User.email == email)).scalar_one_or_none():
                raise HTTPException(status_code=409, detail="That email is already registered.")
            if SIGNUP_MAX_PER_DAY:
                today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                made = s.execute(select(func.count()).select_from(User).where(User.created_at >= today)).scalar_one()
                if made >= SIGNUP_MAX_PER_DAY:
                    alerts.raise_alert("signups", f"{made} accounts were created today (limit {SIGNUP_MAX_PER_DAY}): new sign-ups are paused until tomorrow. "
                                                  "Raise SIGNUP_MAX_PER_DAY if this is real growth, otherwise someone is mass-registering.")
                    raise HTTPException(status_code=503, detail="Sign-ups are very busy today. Please try again tomorrow.")
            user = User(email=email, password_hash=password_hash, daily_minutes=SIGNUP_DAILY_MINUTES, monthly_minutes=SIGNUP_MONTHLY_MINUTES)
            s.add(user)
            s.commit()
    return _session_reply(request, response, user, {"email": email, "is_admin": False, **_quota(user)}, "app", body.cookie)


@app.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    ratelimit.check_password_length(body.password)
    audience = "admin" if body.audience == "admin" else "app"
    if body.cookie:
        auth.check_issue_origin(request, audience)
    email = body.email.strip().lower()[:255]
    keys = ratelimit.login_attempt(request, email)   # counted BEFORE the password check; a correct password gives it back
    with Session() as s:
        user = s.execute(select(User).where(User.email == email)).scalar_one_or_none()
    password_ok = auth.verify_password(body.password, user.password_hash if user else auth.DUMMY_HASH)   # same work for unknown emails
    if not user or not user.is_active or not password_ok:
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    ratelimit.login_succeeded(keys)
    if audience == "admin" and not user.is_admin:
        raise HTTPException(status_code=403, detail="This account is not an admin.")
    if auth.needs_rehash(user.password_hash):   # old, cheaper hash: store a stronger one now that we hold the password
        upgraded = auth.hash_password(body.password)
        with Session() as s:
            row = s.get(User, user.id)
            if row is not None and row.password_hash == user.password_hash:   # not if the password was changed meanwhile
                row.password_hash = upgraded
                s.commit()
    return _session_reply(request, response, user, {"email": user.email, "is_admin": user.is_admin, **_quota(user)}, audience, body.cookie)


@app.post("/api/auth/refresh")
def refresh(request: Request, response: Response, creds=Depends(auth._bearer)):
    """A new token for a valid one. The apps call it every few minutes while open, which is what lets admin tokens be short.
    A cookie session gets a new cookie and a new CSRF token; a bearer session gets the new token in the body."""
    user, token, via, audience = auth.renewed_token(request, creds)
    if via == "cookie":
        auth.set_session_cookie(response, request, token, audience)
        return {"csrf_token": auth.csrf_for(token), "is_admin": user.is_admin}
    return {"token": token, "is_admin": user.is_admin}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """Forget this browser's session cookie. (JavaScript cannot delete an httpOnly cookie, the server has to.) Needs no login: logging out must
    always work, even with an expired session."""
    auth.clear_session_cookie(response, request, auth.audience_of(request.headers))
    return {"ok": True}


@app.post("/api/auth/logout-all")
def logout_all(request: Request, response: Response, user: User = Depends(auth.current_user)):
    """Cancel every session of this account (this device and all others)."""
    with Session() as s:
        row = s.get(User, user.id)
        auth.revoke_tokens(s, row)
        s.commit()
    auth.clear_session_cookie(response, request, auth.audience_of(request.headers))
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request, user: User = Depends(auth.current_user)):
    out = {"id": user.id, "email": user.email, "is_admin": user.is_admin, **_quota(user)}
    if request.state.auth_via == "cookie":   # a page reload lost the CSRF token held in memory: hand it out again (only an allowed origin can read this answer)
        out["csrf_token"] = auth.csrf_for(request.state.token)
    return out


@app.get("/api/usage")
def usage(user: User = Depends(auth.current_user)):
    """The signed-in user's own usage: totals, 30 days of minutes, and their recent videos (for their dashboard)."""
    now = utcnow()
    days = 30
    first = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    with Session() as s:
        rows = s.execute(select(Job).where(Job.user_id == user.id, Job.created_at >= min(first, month_start()))
                         .order_by(Job.created_at.desc())).scalars().all()
        recent = s.execute(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(20)).scalars().all()
        total_videos = s.execute(select(func.count()).select_from(Job).where(Job.user_id == user.id, Job.status == "done")).scalar_one()
    per_day: dict[str, float] = {}
    by_kind = {"recap": 0.0, "full": 0.0, "subtitles": 0.0}
    month_videos = 0
    for j in rows:
        created = j.created_at if j.created_at.tzinfo else j.created_at.replace(tzinfo=timezone.utc)
        if created >= first:
            key = created.strftime("%Y-%m-%d")
            per_day[key] = per_day.get(key, 0.0) + (j.charged_seconds or 0.0) / 60
        if created >= month_start() and (j.charged_seconds or 0) > 0:
            month_videos += 1
            p = j.params or {}
            kind = "subtitles" if p.get("output") == "subtitles" else ("full" if p.get("mode") == "full" else "recap")
            by_kind[kind] += (j.charged_seconds or 0.0) / 60
    series = [{"date": (first + timedelta(days=i)).strftime("%Y-%m-%d"),
               "minutes": round(per_day.get((first + timedelta(days=i)).strftime("%Y-%m-%d"), 0.0), 1)} for i in range(days)]
    nxt_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    nxt_month = (month_start() + timedelta(days=32)).replace(day=1)
    return {
        **_quota(user), "days": series, "minutes_by_kind": {k: round(v, 1) for k, v in by_kind.items()},
        "month_videos": month_videos, "total_videos": total_videos,
        "resets": {"day": nxt_day.isoformat(), "month": nxt_month.isoformat()},
        "recent": [{"id": j.id, "created_at": (j.created_at if j.created_at.tzinfo else j.created_at.replace(tzinfo=timezone.utc)).isoformat(), "status": j.status,
                    "minutes": round((j.charged_seconds or 0.0) / 60, 1),
                    "kind": "edit" if (j.params or {}).get("edit") else ("subtitles" if (j.params or {}).get("output") == "subtitles"
                                                                          else ("full" if (j.params or {}).get("mode") == "full" else "recap")),
                    "aspect": (j.params or {}).get("aspect", "original")} for j in recent],
    }


# ---------- voices (public) ----------

@app.get("/api/voices")
def list_voices():
    """Voice catalogue with pre-generated sample URLs (only voices whose sample file exists)."""
    return [
        {**v, "sample_url": f"/api/voice-samples/{v['name']}.wav"}
        for v in VOICES if os.path.exists(os.path.join(SAMPLES_DIR, f"{v['name']}.wav"))
    ]


@app.get("/api/voice-samples/{filename}")
def voice_sample(filename: str):
    name = filename.removesuffix(".wav")
    path = os.path.join(SAMPLES_DIR, f"{name}.wav")
    if name not in VOICE_NAMES or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sample not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{name}-sample.wav",
                        headers={"Cache-Control": "public, max-age=604800"})


LOOK_SAMPLES_DIR = "look_samples"


@app.get("/api/looks")
def list_looks():
    """Character looks (baby, monster, animal...) whose sample exists: base voice + performance instruction."""
    from looks import LOOKS
    return [{"id": i, "group": g, "label": lab, "voice": v, "sample_url": f"/api/look-samples/{i}.wav"}
            for i, g, lab, v, _ in LOOKS if os.path.exists(os.path.join(LOOK_SAMPLES_DIR, f"{i}.wav"))]


@app.get("/api/look-samples/{filename}")
def look_sample(filename: str):
    from looks import LOOK_IDS
    name = filename.removesuffix(".wav")
    path = os.path.join(LOOK_SAMPLES_DIR, f"{name}.wav")
    if name not in LOOK_IDS or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sample not found.")
    return FileResponse(path, media_type="audio/wav", filename=f"{name}-sample.wav",
                        headers={"Cache-Control": "public, max-age=604800"})


# ---------- jobs ----------

def save_upload(upload: UploadFile, directory: str, max_mb: int) -> str:
    """Store an upload under a unique name; refuse files over the size limit."""
    ext = os.path.splitext(os.path.basename(upload.filename or ""))[1][:10]
    path = os.path.join(directory, f"{uuid.uuid4().hex}{ext}")
    limit, size = max_mb * 1024 * 1024, 0
    try:
        with open(path, "wb") as buffer:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"File is larger than {max_mb} MB.")
                buffer.write(chunk)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return path


def _clean_blurs(raw: str) -> list:
    """Parse the preview's blur boxes; keep at most 6 sane [x, y, w, h] fractions."""
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


@app.post("/api/jobs")
def create_job(
    user: User = Depends(auth.current_user),
    video_file: UploadFile = File(None),
    custom_logo: UploadFile = File(None),
    voice_type: str = Form("su"),
    target_language: str = Form("my"),
    # sync policy
    allow_voice_speedup: bool = Form(True),
    max_voice_speedup: float = Form(1.35),
    min_video_speed: float = Form(0.85),
    fit_translation: bool = Form(True),
    keep_background: bool = Form(False),
    # product modes
    mode: str = Form("recap"),            # recap: one narrator voice | full: characters with their own voices + emotions
    output: str = Form("dub"),            # dub: Burmese voice-over | subtitles: keep the original sound, Burmese subtitles only
    background: str = Form(""),           # "", original (lowered under the voice), separate (Demucs), off
    soft_music: bool = Form(False),       # optional quiet generated pad under everything
    emotion: bool = Form(True),           # full mode: voice lines with a delivery direction (angry, sad, ...)
    # effects
    blur_subtitles: bool = Form(True),
    enable_subtitles: bool = Form(True),
    remove_watermark: bool = Form(False),
    enable_flip: bool = Form(False),
    flip_vertical: bool = Form(False),
    video_speed: float = Form(1.0),
    brightness: float = Form(0.0),
    contrast: float = Form(1.0),
    saturation: float = Form(1.0),
    logo_position: str = Form("top-right"),
    logo_size: float = Form(0.15),
    logo_x: float = Form(-1.0),           # dragged logo position: left edge as a fraction of video width (-1 = use logo_position)
    logo_y: float = Form(-1.0),           # top edge as a fraction of video height
    aspect: str = Form("original"),       # final frame: original | 9:16 | 1:1 | 4:5 | 16:9
    fit_mode: str = Form("blur"),         # blur: whole picture over a blurred copy | crop: fill the frame
    pan_x: float = Form(0.5),             # crop mode: which part is kept (0..1)
    pan_y: float = Form(0.5),
    manual_blurs: str = Form(""),         # JSON [[x,y,w,h],...] fractions of the frame, blurred for the whole video
):
    if runtime_settings.maintenance():
        raise HTTPException(status_code=503, detail="We're temporarily not accepting new videos. Please try again later.")
    if not video_file:
        raise HTTPException(status_code=400, detail="No video file provided.")
    if mode not in ("recap", "full") or output not in ("dub", "subtitles") or background not in ("", "original", "separate", "off"):
        raise HTTPException(status_code=400, detail="Unknown mode, output or background option.")
    if aspect not in ("original", "9:16", "1:1", "4:5", "16:9") or fit_mode not in ("blur", "crop"):
        raise HTTPException(status_code=400, detail="Unknown video format.")
    if output == "dub":
        _refuse_if_voice_limit()
    if tts_provider() == "gemini" and voice_type != "su" and voice_type not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice_type}")
    if tts_provider() == "elevenlabs" and voice_type != "su":
        raise HTTPException(status_code=400, detail=f"Unsupported voice selection: {voice_type}")
    params = {"voice_type": voice_type, "target_language": target_language,
              "allow_voice_speedup": allow_voice_speedup, "max_voice_speedup": max_voice_speedup,
              "min_video_speed": min_video_speed, "fit_translation": fit_translation,
              "keep_background": keep_background, "mode": mode, "output": output, "background": background,
              "soft_music": soft_music, "emotion": emotion, "blur_subtitles": blur_subtitles,
              "enable_subtitles": enable_subtitles, "remove_watermark": remove_watermark,
              "enable_flip": enable_flip, "flip_vertical": flip_vertical, "video_speed": video_speed,
              "brightness": brightness, "contrast": contrast, "saturation": saturation,
              "logo_position": logo_position, "logo_size": logo_size,
              "logo_x": logo_x, "logo_y": logo_y, "manual_blurs": _clean_blurs(manual_blurs),
              "aspect": aspect, "fit_mode": fit_mode, "pan_x": pan_x, "pan_y": pan_y}

    with Session() as s:
        if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")

    video_path = save_upload(video_file, UPLOAD_DIR, MAX_UPLOAD_MB)
    logo_path = save_upload(custom_logo, LOGOS_DIR, 20) if custom_logo else None
    try:
        try:
            seconds = upload_duration(video_path)
        except safe_media.UnsafeMedia as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            raise HTTPException(status_code=400, detail="That file doesn't look like a valid video.")
        if logo_path:   # decode + re-save as a fresh PNG: the uploaded bytes never reach ffmpeg
            try:
                logo_path = safe_media.clean_logo(logo_path)
            except safe_media.UnsafeMedia as exc:
                logo_path = None
                raise HTTPException(status_code=400, detail=str(exc))
        if seconds > MAX_VIDEO_MINUTES * 60:
            raise HTTPException(status_code=413, detail=f"Videos can be at most {MAX_VIDEO_MINUTES:g} minutes long.")
        job_id = uuid.uuid4().hex[:12]
        with Session() as s:
            with capacity.lock:   # ONE critical section: re-check every limit, decide, create the job. Parallel uploads cannot all pass.
                lock_admission(s)
                _check_limits(s, user, seconds)
                verdict = capacity.decide(s, seconds, params.get("output"), params.get("mode"))
                if not verdict["ok"]:
                    capacity.refuse(verdict["reason"])
                params = {**params, "reserved_model": verdict["model"], "reserved_requests": verdict["requests"]}
                input_key = storage.put(video_path, "uploads")
                logo_key = storage.put(logo_path, "logos") if logo_path else None
                s.add(Job(id=job_id, user_id=user.id, status="queued", params=params, data={},
                          input_key=input_key, logo_key=logo_key, charged_seconds=seconds))
                s.commit()
    except Exception:
        for p in (video_path, logo_path):
            if p and os.path.exists(p):
                os.remove(p)
        raise
    jobs_queue.enqueue(job_id)
    return {"job_id": job_id}


def _check_limits(s, user: User, seconds: float):
    """Per-user and global limits. Must run inside the admission lock, in the same transaction that creates the job."""
    if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:
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


def _refuse_if_voice_limit():
    """Don't accept work (and spend minutes + other quotas) while Gemini's daily voice limit is used up."""
    if tts_provider() == "gemini":
        import tts_pool
        if tts_pool.all_blocked():
            raise HTTPException(status_code=503, detail=tts_pool.blocked_message())


def _file_url(key: str, download: bool) -> str:
    name = os.path.basename(key)
    if storage.BACKEND == "s3":
        return storage.presigned_url(key, name if download else None)
    exp, sig = auth.sign_file(name, SIGNED_URL_SECONDS)
    return f"/api/files/{name}?exp={exp}&sig={sig}" + ("&dl=1" if download else "")


@app.exception_handler(Exception)
async def _unexpected_error(request: Request, exc: Exception):
    """Anything nobody planned for: log it with a code, tell the caller only the code (never a traceback, path or SQL)."""
    import traceback
    ref = uuid.uuid4().hex[:8]
    print(f"[error {ref}] {request.method} {request.url.path}\n{''.join(traceback.format_exception(exc))}", flush=True)
    return JSONResponse(status_code=500, content={"detail": f"Something went wrong. Please try again. If it keeps happening, quote this code: {ref}"})


WORKERS = int(os.getenv("QUEUE_WORKERS", os.getenv("RECAP_WORKERS", "2")))  # jobs that run at the same time
DEFAULT_JOB_SECONDS = 300.0


def _queue_info(job: Job) -> dict:
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


_HIDDEN_FROM_USERS = ("result", "started_at", "run_seconds", "usage", "error_detail")   # internals: cost, raw error text


def _job_view(job: Job) -> dict:
    view = {"id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "error": job.error, **{k: v for k, v in (job.data or {}).items() if k not in _HIDDEN_FROM_USERS}}
    if job.status == "queued":
        view.update(_queue_info(job))
    result = (job.data or {}).get("result")
    if result:
        result = dict(result)
        if result.get("video_file") and storage.output_exists(result["video_file"]):
            result["video_url"] = _file_url(result["video_file"], False)
            result["download_url"] = _file_url(result["video_file"], True)
            result["subtitle_url"] = _file_url(result["subtitle_file"], True)
        else:
            result["expired"] = True  # files are deleted after FILE_TTL_HOURS
        view["result"] = result
    return view


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(auth.current_user)):
    with Session() as s:
        job = s.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown job")
    return _job_view(job)


@app.get("/api/files/{filename}")
def get_file(filename: str, exp: int, sig: str, dl: int = 0):
    name = os.path.basename(filename)
    if not auth.check_signature(name, exp, sig):
        raise HTTPException(status_code=403, detail="Link expired. Reload the page to get a new one.")
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found (results are kept for %g hours)." % FILE_TTL_HOURS)
    media_type = "application/x-subrip" if name.endswith(".srt") else "video/mp4"
    return FileResponse(path, media_type=media_type, filename=name if dl else None)


# ---------- editor: re-render a finished job with edited lines ----------

class EditLine(BaseModel):
    id: int | None = None                            # id of the project line this edit comes from (None = new line)
    speaker: str | None = Field(None, max_length=8)   # full mode: which character speaks (None = same as before / previous line)
    start: float = Field(ge=0)                       # source-video time where this line's scene begins
    text: str = Field(max_length=800)
    source_text: str = Field("", max_length=2000)
    tempo: float | None = Field(None, ge=0.7, le=1.6)  # fixed voice speed for this line (None = automatic)


class RerenderBody(BaseModel):
    segments: list[EditLine] = Field(min_length=1, max_length=600)
    voice_type: str | None = None
    speaker_voices: dict[str, str] | None = None     # full mode: new voice per character
    # "finishing" settings, chosen after the first result: None = keep what the job had
    blur_subtitles: bool | None = None
    enable_subtitles: bool | None = None
    remove_watermark: bool | None = None
    enable_flip: bool | None = None
    bg_volume: float | None = Field(default=None, ge=0.0, le=1.5)   # level of the film's own music/effects under the voice


@app.post("/api/jobs/{job_id}/rerender")
def rerender(job_id: str, body: RerenderBody, user: User = Depends(auth.current_user)):
    """New job from a finished one: same source video and settings, edited lines. Unchanged lines reuse their
    cached voice clips, so only edited lines cost a TTS request."""
    if runtime_settings.maintenance():
        raise HTTPException(status_code=503, detail="We're temporarily not accepting new work. Please try again later.")
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job")
        if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")
    project = ((job.data or {}).get("result") or {}).get("project")
    if (job.params or {}).get("output", "dub") == "dub":
        _refuse_if_voice_limit()
    if job.status != "done" or not project:
        raise HTTPException(status_code=400, detail="This video can't be edited (finish it first, or it was made before the editor existed).")
    if storage.BACKEND == "local" and not os.path.isfile(job.input_key):
        raise HTTPException(status_code=410, detail=f"The source video was deleted after {FILE_TTL_HOURS:g} hours. Upload it again.")
    voice = body.voice_type or project["voice"]
    if tts_provider() == "gemini" and voice != "su" and voice not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice}")
    limit = float(project["source_duration"])
    lines = sorted((l for l in body.segments if l.text.strip()), key=lambda l: l.start)
    if not lines or lines[-1].start > limit:
        raise HTTPException(status_code=400, detail="Line times must be inside the video.")
    params = dict(job.params or {})
    params["voice_type"] = voice
    for key in ("blur_subtitles", "enable_subtitles", "remove_watermark", "enable_flip", "bg_volume"):
        if getattr(body, key) is not None:
            params[key] = getattr(body, key)
    params.pop("reserved_model", None); params.pop("reserved_requests", None)   # the first run's voice reservation is not this job's
    params["bg_source_job"] = params.get("bg_source_job") or job_id   # re-renders reuse this video's separated background
    old = {sg["id"]: sg for sg in project["segments"]}
    speakers = {k: dict(v) for k, v in (project.get("speakers") or {}).items()}
    for sid, v in (body.speaker_voices or {}).items():
        if sid in speakers and looks.valid(v):
            speakers[sid]["voice"] = v
    edit_lines = []
    for l in lines:
        d = l.model_dump()
        src = old.get(l.id) if l.id is not None else None
        if src:   # carry what the editor doesn't send: character, emotion, delivery style (a changed text keeps the same style)
            d["speaker"] = d.get("speaker") or src.get("speaker")
            d["emotion"], d["style"] = src.get("emotion"), src.get("style")
        edit_lines.append(d)
    params["edit"] = {"segments": edit_lines, "speakers": speakers or None, "fx": project["fx"],
                      "source_language": project.get("source_language"),
                      "cuts": project.get("cuts", []), "voice_model": project.get("voice_model"),
                      "tts_model": project.get("tts_model")}
    new_id = uuid.uuid4().hex[:12]
    with Session() as s:
        with capacity.lock:
            lock_admission(s)
            if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:   # re-checked under the lock: parallel clicks cannot pass together
                raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")
            edit_limits.record(s, user.id, edit_limits.video_id(job), "rerender")   # per-video + per-day cap, committed with the job
            s.add(Job(id=new_id, user_id=user.id, status="queued", params=params, data={},
                      input_key=job.input_key, logo_key=job.logo_key, charged_seconds=0.0))
            s.commit()
    jobs_queue.enqueue(new_id)
    return {"job_id": new_id}


class PreviewBody(BaseModel):
    id: int | None = None                  # project line (its emotion direction is used, so Apply reuses the clip)
    text: str = Field(max_length=800)
    voice: str = Field(max_length=40)      # voice name to hear it in (e.g. the voice of the character you picked)


@app.post("/api/jobs/{job_id}/preview-line")
def preview_line(job_id: str, body: PreviewBody, user: User = Depends(auth.current_user)):
    """Hear ONE line in a chosen voice before pressing Apply: one TTS request, cached for the render."""
    if not looks.valid(body.voice):
        raise HTTPException(status_code=400, detail=f"Unknown voice: {body.voice}")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="This line has no text.")
    with Session() as s:
        job = s.get(Job, job_id)
    project = ((job.data or {}).get("result") or {}).get("project") if job and job.user_id == user.id else None
    if not project:
        raise HTTPException(status_code=404, detail="Unknown job")
    _refuse_if_voice_limit()
    src = next((sg for sg in project["segments"] if sg["id"] == body.id), None) if body.id is not None else None
    import pipeline
    used = []   # counted only when a voice request is really about to be sent (cached clips are free); given back if it fails
    try:
        path = pipeline.preview_line(body.text.strip(), body.voice, (src or {}).get("style"),
                                     project.get("voice_model") or {}, project.get("tts_model"), (job.params or {}).get("mode"),
                                     before_spend=lambda: used.append(edit_limits.charge(user.id, edit_limits.video_id(job), "preview")))
    except HTTPException:
        raise
    except Exception as exc:
        for use_id in used:
            edit_limits.refund(use_id)
        print(f"[preview {job_id}] failed: {exc!r}", flush=True)   # the real reason stays in the server log
        if isinstance(exc, pipeline.LineBlocked):
            raise HTTPException(status_code=422, detail="The voice service refused this line. Try different wording.")
        raise HTTPException(status_code=502, detail="Voice preview failed. Please try again in a moment.")
    return FileResponse(path, media_type="audio/wav")


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: User = Depends(auth.current_user)):
    """Stop a queued or running job. The worker notices at its next step and quits; nothing is charged."""
    from db import update_job
    with Session() as s:
        job = s.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown job")
    if job.status in ("queued", "running"):
        update_job(job_id, status="cancelled", stage="Cancelled")
    return {"status": "cancelled" if job.status in ("queued", "running") else job.status}
