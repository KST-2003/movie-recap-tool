import json
from config import (ALLOW_SIGNUP, CORS_ORIGINS, DEFAULT_DAILY_MINUTES,
                    LOGOS_DIR, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES,
                    OUTPUT_DIR, SIGNED_URL_SECONDS, UPLOAD_DIR)

import os
import re
import threading
import time
import uuid

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from datetime import timedelta, timezone

from sqlalchemy import func, select, update

import alerts
import auth
from admin import router as admin_router, settings as runtime_settings
import capacity
import usage as usage_log   # (main.py has an endpoint function called usage)
import jobs_queue
import looks
import storage
import topup
from common import media_duration, tts_provider
from db import Job, Session, User, active_jobs, failure_wait_seconds, month_start, refund_credit, user_role, used_seconds_month, used_seconds_today, utcnow
from voices import VOICES, VOICE_NAMES

import logging


class _QuietPolling(logging.Filter):
    """The page polls /api/jobs/<id> every 1.5 s; those lines bury everything useful in the terminal."""
    def filter(self, record):
        msg = record.getMessage()
        return not ("GET /api/jobs/" in msg and '" 200' in msg)


logging.getLogger("uvicorn.access").addFilter(_QuietPolling())

usage_log.install()
app = FastAPI(title="Movie Recap Tool Backend", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin_router)
app.include_router(topup.router)

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
            refund_credit(s, job)
            job.error = "The server was restarted while this video was processing. Please upload it again."
        s.commit()
        if stuck:
            print(f"[startup] marked {len(stuck)} interrupted job(s) as failed", flush=True)


@app.on_event("startup")
def _startup():
    _fail_orphaned_jobs()
    if storage.BACKEND == "local":
        threading.Thread(target=_cleanup_loop, daemon=True).start()


@app.get("/")
def read_root():
    return {"message": "Movie Recap Tool API", "version": app.version}


@app.get("/health")
def health():
    return {"ok": True}


# ---------- accounts ----------

class Credentials(BaseModel):
    email: str                     # the login name ("username"; older accounts use an email address)
    password: str
    device_id: str | None = None   # random id the browser keeps; used for the "one device per login" rule


def _quota(user: User) -> dict:
    with Session() as s:
        used = used_seconds_today(s, user.id)
        month_used = used_seconds_month(s, user.id)
        blocked = failure_wait_seconds(s, user.id)
    day_left = max(0, user.daily_minutes * 60 - used)
    month_left = max(0, user.monthly_minutes * 60 - month_used)
    credit = max(0.0, user.credit_seconds or 0.0)
    return {"daily_minutes": user.daily_minutes, "used_seconds": round(used), "remaining_seconds": round(min(day_left, month_left) + credit),
            "allowance_remaining_seconds": round(min(day_left, month_left)), "credit_seconds": round(credit),
            "monthly_minutes": user.monthly_minutes, "month_used_seconds": round(month_used),
            "month_remaining_seconds": round(month_left), "day_remaining_seconds": round(day_left),
            "upload_blocked_seconds": 0 if user.is_admin else round(blocked)}


@app.post("/api/auth/register")
def register(body: Credentials, request: Request):
    auth.rate_limit(request)
    if not ALLOW_SIGNUP:
        raise HTTPException(status_code=403, detail="Sign-ups are closed.")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    with Session() as s:
        if s.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise HTTPException(status_code=409, detail="That email is already registered.")
        user = User(email=email, password_hash=auth.hash_password(body.password), daily_minutes=DEFAULT_DAILY_MINUTES)
        s.add(user)
        s.flush()
        device_id = auth.clean_device_id(body.device_id)
        auth.register_device(s, user, device_id, request)
        s.commit()
    return {"token": auth.make_token(user, device_id), "device_id": device_id, "email": email, "is_admin": False, **_quota(user)}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    auth.rate_limit(request)
    with Session() as s:
        user = s.execute(select(User).where(User.email == body.email.strip().lower())).scalar_one_or_none()
        if not user or not auth.verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Wrong username or password.")
        if user.status != "active":   # the password was right, so it is safe to say why the login does not work
            raise HTTPException(status_code=403, detail=auth.STATUS_MESSAGES.get(user.status, "Account unavailable."))
        device_id = auth.clean_device_id(body.device_id)
        auth.register_device(s, user, device_id, request)   # may refuse: this login is limited to N devices
        s.commit()
    return {"token": auth.make_token(user, device_id), "device_id": device_id, "email": user.email, "is_admin": user.is_admin, "is_superadmin": user.is_superadmin, "role": user_role(user), **_quota(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(auth.current_user)):
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin, "is_superadmin": user.is_superadmin, "role": user_role(user), **_quota(user)}


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


@app.get("/api/voice-quality")
def voice_quality_options():
    """Which voice qualities can be chosen: premium (Gemini) always, standard (Azure) only when it is set up."""
    import audio_tools
    import azure_tts
    return {"premium": True, "standard": azure_tts.enabled(), "separation": audio_tools.separation_available()}


@app.get("/api/azure-samples/{gender}.wav")
def azure_sample(gender: str):
    """A short sample of the Standard voice (made once, then kept)."""
    import azure_tts
    if gender not in ("female", "male") or not azure_tts.enabled():
        raise HTTPException(status_code=404, detail="No sample.")
    path = os.path.join(SAMPLES_DIR, f"azure-{gender}.wav")
    if not os.path.isfile(path):
        from voices import SAMPLE_TEXT
        os.makedirs(SAMPLES_DIR, exist_ok=True)
        try:
            azure_tts.synthesize(SAMPLE_TEXT, path, "Charon" if gender == "male" else "Kore")
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Sample failed: {str(exc)[:120]}")
    return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "public, max-age=604800"})


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
    voice_quality: str = Form("premium"), # premium: Gemini voices (30, emotion) | standard: Azure Neural (2 Burmese voices, cheaper, more usage)
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
    device_render: bool = Form(False),    # the phone draws the picture (WebCodecs); the server only returns a plan + the sound
    resolution: int = Form(720),          # output size: 720 (faster render, recommended) | 1080 = short side in pixels
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
    if voice_quality not in ("premium", "standard"):
        raise HTTPException(status_code=400, detail="Unknown voice quality.")
    if voice_quality == "standard":
        import azure_tts
        if output == "dub" and not azure_tts.enabled():
            raise HTTPException(status_code=400, detail="The Standard voice is not available right now.")
        emotion = False   # Azure has no emotion directions
    if aspect not in ("original", "9:16", "1:1", "4:5", "16:9") or fit_mode not in ("blur", "crop"):
        raise HTTPException(status_code=400, detail="Unknown video format.")
    if resolution not in (720, 1080):
        raise HTTPException(status_code=400, detail="Unknown video size.")
    if output == "dub":
        _refuse_if_voice_limit()
    if tts_provider() == "gemini" and voice_type != "su" and voice_type not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice_type}")
    if tts_provider() == "elevenlabs" and voice_type != "su":
        raise HTTPException(status_code=400, detail=f"Unsupported voice selection: {voice_type}")
    params = {"voice_type": voice_type, "target_language": target_language,
              "allow_voice_speedup": allow_voice_speedup, "max_voice_speedup": max_voice_speedup,
              "min_video_speed": min_video_speed, "fit_translation": fit_translation,
              "keep_background": keep_background, "mode": mode, "output": output, "voice_quality": voice_quality, "background": background,
              "soft_music": soft_music, "emotion": emotion, "blur_subtitles": blur_subtitles,
              "enable_subtitles": enable_subtitles, "remove_watermark": remove_watermark,
              "enable_flip": enable_flip, "flip_vertical": flip_vertical, "video_speed": video_speed,
              "brightness": brightness, "contrast": contrast, "saturation": saturation,
              "logo_position": logo_position, "logo_size": logo_size,
              "logo_x": logo_x, "logo_y": logo_y, "manual_blurs": _clean_blurs(manual_blurs),
              "device_render": device_render, "resolution": resolution, "aspect": aspect, "fit_mode": fit_mode, "pan_x": pan_x, "pan_y": pan_y,
              "filename": os.path.basename(video_file.filename or "")[:120]}   # shown in "My videos"

    with Session() as s:
        _refuse_if_failing(s, user)
        if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")

    video_path = save_upload(video_file, UPLOAD_DIR, MAX_UPLOAD_MB)
    logo_path = save_upload(custom_logo, LOGOS_DIR, 20) if custom_logo else None
    try:
        try:
            seconds = media_duration(video_path)
        except Exception:
            raise HTTPException(status_code=400, detail="That file doesn't look like a valid video.")
        if seconds > MAX_VIDEO_MINUTES * 60:
            raise HTTPException(status_code=413, detail=f"Videos can be at most {MAX_VIDEO_MINUTES:g} minutes long.")
        job_id = uuid.uuid4().hex[:12]
        with Session() as s:
            month_used, used = used_seconds_month(s, user.id), used_seconds_today(s, user.id)
            free = max(0.0, min(user.daily_minutes * 60 - used, user.monthly_minutes * 60 - month_used))   # allowance left right now
            credit_part = max(0.0, seconds - free)   # what the allowance cannot cover is paid with bought minutes
            if credit_part > 0:
                have = max(0.0, s.get(User, user.id).credit_seconds or 0.0)
                if have + 1e-6 < credit_part:
                    raise HTTPException(status_code=402, detail=(
                        "Your available minutes are not enough for this video. Please top up minutes to make it."))
            cap = runtime_settings.global_daily_minutes()
            if cap and used_seconds_today(s, None, True) + seconds > cap * 60:
                raise HTTPException(status_code=503, detail="We've reached today's capacity. Please try again tomorrow.")
            with capacity.lock:   # decide + create the job as one step, so a burst of uploads cannot all be admitted
                verdict = capacity.decide(s, seconds, params.get("output"), params.get("voice_quality"))
                if not verdict["ok"]:
                    capacity.refuse(verdict["reason"], params.get("voice_quality"))
                params = {**params, "reserved_model": verdict["model"], "reserved_requests": verdict["requests"]}
                input_key = storage.put(video_path, "uploads")
                logo_key = storage.put(logo_path, "logos") if logo_path else None
                if credit_part > 0:   # take the bought minutes in the same step (a second upload at the same moment cannot spend them twice)
                    taken = s.execute(update(User).where(User.id == user.id, User.credit_seconds >= credit_part - 1e-6)
                                      .values(credit_seconds=User.credit_seconds - credit_part)).rowcount
                    if not taken:
                        raise HTTPException(status_code=402, detail="Your available minutes are not enough for this video. Please top up minutes to make it.")
                s.add(Job(id=job_id, user_id=user.id, status="queued", params=params, data={},
                          input_key=input_key, logo_key=logo_key, charged_seconds=seconds - credit_part, credit_seconds=credit_part))
                s.commit()
    except Exception:
        for p in (video_path, logo_path):
            if p and os.path.exists(p):
                os.remove(p)
        raise
    jobs_queue.enqueue(job_id)
    return {"job_id": job_id}


def _refuse_if_failing(s, user: User):
    """Several failed / cancelled videos that already spent paid tokens in a short time: wait a few hours (their minutes were refunded, our API bill was not)."""
    if user.is_admin:
        return
    wait = failure_wait_seconds(s, user.id)
    if wait > 0:
        alerts.raise_alert(f"failures:{user.id}", f"User {user.email} tried to upload while paused after repeated failed or cancelled videos.")
        h, m = int(wait // 3600), int(wait % 3600 // 60) + 1
        raise HTTPException(status_code=429, detail=f"Too many videos failed or were cancelled recently. You can start a new video in about {h} h {m} min." if h else
                            f"Too many videos failed or were cancelled recently. You can start a new video in about {m} min.")


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


FRIENDLY_BUSY = "Our service is very busy right now, so we couldn't finish this video. Your minutes were refunded. Please try again a little later."
FRIENDLY_FAILED = "We couldn't finish this video this time. Our team has been notified and your minutes were refunded. Please try again a little later."
_BUSY_WORDS = ("quota", "rate", "429", "busy", "capacity", "exhausted", "too slow", "time limit", "timed out", "overloaded", "unavailable", "503")


def friendly_error(raw: str | None) -> str | None:
    """What the USER sees for a failed video: a calm notice, never raw errors or numbers. The admin sees the full text (job detail)."""
    if not raw:
        return None
    low = raw.lower()
    return FRIENDLY_BUSY if any(w in low for w in _BUSY_WORDS) else FRIENDLY_FAILED


_ADMIN_ONLY = ("result", "started_at", "run_seconds", "error_detail", "log", "stages", "failed_stage", "usage", "device_render")


def _job_view(job: Job) -> dict:
    view = {"id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "error": friendly_error(job.error) if job.status == "error" else job.error,
            **{k: v for k, v in (job.data or {}).items() if k not in _ADMIN_ONLY}}
    if job.status == "queued":
        view.update(_queue_info(job))
    result = (job.data or {}).get("result")
    if result:
        result = dict(result)
        if result.get("device_plan"):   # made on the user's phone: the picture does not exist on the server, only the sound + plan
            if result.get("audio_file") and storage.output_exists(result["audio_file"]):
                result["audio_url"] = _file_url(result["audio_file"], False)
                result["subtitle_url"] = _file_url(result["subtitle_file"], True)
            else:
                result["expired"] = True
        elif result.get("video_file") and storage.output_exists(result["video_file"]):
            result["video_url"] = _file_url(result["video_file"], False)
            result["download_url"] = _file_url(result["video_file"], True)
            result["subtitle_url"] = _file_url(result["subtitle_file"], True)
        else:
            result["expired"] = True  # files are deleted after the retention window (admin setting)
        view["result"] = result
    return view


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(auth.current_user)):
    with Session() as s:
        job = s.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown job")
    return _job_view(job)


def _history_row(job: Job) -> dict:
    params, data = job.params or {}, job.data or {}
    result = data.get("result") or {}
    project = result.get("project") or {}
    video_ok = bool(result.get("video_file")) and storage.output_exists(result["video_file"])
    finished = job.finished_at or job.created_at
    finished = finished if finished.tzinfo else finished.replace(tzinfo=timezone.utc)
    kind = "edit" if params.get("edit") else ("subtitles" if params.get("output") == "subtitles" else params.get("mode", "recap"))
    return {"id": job.id, "status": job.status, "title": params.get("filename") or "", "kind": kind, "aspect": params.get("aspect", "original"),
            "minutes": round(float(project.get("source_duration") or (job.charged_seconds or 0)) / 60, 1),
            "created_at": (job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)).isoformat(), "video_available": video_ok,
            "can_edit": bool(video_ok and project and storage.source_exists(job.input_key)),
            "expires_at": (finished + timedelta(days=runtime_settings.keep_result_days())).isoformat() if video_ok else None,
            "error": friendly_error(job.error) if job.status == "error" else None}


@app.get("/api/jobs")
def my_videos(page: int = 1, per_page: int = 20, user: User = Depends(auth.current_user)):
    """The user's own video history: kept as a list for ever (small); the video file itself only for the keeping time."""
    per_page, page = min(max(per_page, 1), 50), max(page, 1)
    with Session() as s:
        jobs = s.execute(select(Job).where(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(1000)).scalars().all()
    jobs = [j for j in jobs if not (j.data or {}).get("user_deleted") and j.status != "cancelled"]   # a cancelled video has nothing to show
    return {"total": len(jobs), "page": page, "per_page": per_page,
            "keep_result_days": runtime_settings.keep_result_days(), "keep_source_days": runtime_settings.keep_source_days(),
            "items": [_history_row(j) for j in jobs[(page - 1) * per_page: page * per_page]]}


@app.delete("/api/jobs/{job_id}")
def delete_my_video(job_id: str, user: User = Depends(auth.current_user)):
    """Remove a video from the user's history and delete its files now (saves storage). The minutes it used stay counted."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job")
        if job.status in ("queued", "running"):
            raise HTTPException(status_code=409, detail="This video is still processing. Cancel it first.")
        result = (job.data or {}).get("result") or {}
        for key in (result.get("video_file"), result.get("audio_file"), result.get("subtitle_file")):
            if key:
                storage.delete_output(key)
        data = {**(job.data or {}), "user_deleted": True}
        data.pop("result", None)   # also drops the stored script (private text)
        job.data = data
        shared = s.execute(select(Job).where(Job.input_key == job.input_key, Job.id != job.id)).scalars().all()
        if not any(not (j.data or {}).get("user_deleted") for j in shared):   # edits share the source: delete it with the last one
            storage.delete_source(job.input_key)
            if job.logo_key:
                storage.delete_source(job.logo_key)
        s.commit()
    return {"deleted": True}


@app.get("/api/files/{filename}")
def get_file(filename: str, exp: int, sig: str, dl: int = 0):
    name = os.path.basename(filename)
    if not auth.check_signature(name, exp, sig):
        raise HTTPException(status_code=403, detail="Link expired. Reload the page to get a new one.")
    path = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found: this video was removed after the keeping time.")
    media_type = "application/x-subrip" if name.endswith(".srt") else ("audio/mp4" if name.endswith(".m4a") else "video/mp4")
    return FileResponse(path, media_type=media_type, filename=name if dl else None)


@app.get("/api/queue")
def queue_status(user: User = Depends(auth.current_user)):
    """Would a video started now have to wait? The app then offers to render the picture on the user's phone instead."""
    with Session() as s:
        running = s.execute(select(func.count()).select_from(Job).where(Job.status == "running")).scalar_one()
        queued = s.execute(select(func.count()).select_from(Job).where(Job.status == "queued")).scalar_one()
        recent = s.execute(select(Job.data).where(Job.status == "done").order_by(Job.finished_at.desc()).limit(20)).scalars().all()
    runs = [d["run_seconds"] for d in recent if d and d.get("run_seconds")]
    avg = sum(runs) / len(runs) if runs else DEFAULT_JOB_SECONDS
    waiting = max(queued + running - WORKERS + 1, 0)
    wait = int(waiting * avg / WORKERS)
    return {"busy": wait >= 60, "wait_seconds": wait, "queued": queued, "running": running}


class DeviceLog(BaseModel):
    ok: bool
    seconds: float | None = None
    speed: float | None = None
    error: str | None = Field(None, max_length=400)
    fell_back: bool = False
    info: dict | None = None             # small device facts: cores, memory hint, test fps, user agent


@app.post("/api/jobs/{job_id}/device-log")
def device_log(job_id: str, body: DeviceLog, user: User = Depends(auth.current_user)):
    """How the on-device render went (to measure the success rate per device before making it the default)."""
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job")
        data = dict(job.data or {})
        info = {k: (str(v)[:200] if not isinstance(v, (int, float, bool)) else v) for k, v in (body.info or {}).items()}
        data["device_render"] = {**body.model_dump(exclude={"info"}), "info": info, "at": time.time()}
        job.data = data
        s.commit()
    print(f"[job {job_id}] device render {'OK' if body.ok else 'FAILED'}: {body.seconds}s speed {body.speed} {body.error or ''} {info}", flush=True)
    return {"ok": True}


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
    device_render: bool | None = None                # True: the phone draws the picture again; False: the server renders (fallback)
    bg_volume: float | None = Field(default=None, ge=0.0, le=1.5)   # level of the film's own music/effects under the voice
    blur_windows: list[list[float]] | None = Field(default=None, max_length=400)   # [[start, end]] SOURCE seconds when the subtitle blur is ON (the editor's blur track); [] = never


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
        raise HTTPException(status_code=410, detail="The source video was removed after its keeping time, so it can't be edited any more. Upload it again.")
    storage.touch(job.input_key)   # editing counts as using it: the keeping time starts again
    voice = body.voice_type or project["voice"]
    if tts_provider() == "gemini" and voice != "su" and voice not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice}")
    limit = float(project["source_duration"])
    lines = sorted((l for l in body.segments if l.text.strip()), key=lambda l: l.start)
    if not lines or lines[-1].start > limit:
        raise HTTPException(status_code=400, detail="Line times must be inside the video.")
    params = dict(job.params or {})
    params["voice_type"] = voice
    for key in ("blur_subtitles", "enable_subtitles", "remove_watermark", "enable_flip", "bg_volume", "device_render"):
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
    fx = dict(project["fx"])
    if body.blur_windows is not None:   # the blur track of the editor: the band stays where it was found, only WHEN it is blurred changes
        top = float(project.get("source_duration") or 0) + 1.0
        wins = sorted((max(0.0, a), min(b, top)) for a, b in (w[:2] for w in body.blur_windows if len(w) >= 2) if b > a and a < top)
        merged: list[list[float]] = []
        for a, b in wins:
            if merged and a <= merged[-1][1] + 0.05:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([round(a, 2), round(b, 2)])
        fx["subtitle_windows"] = [[round(a, 2), round(b, 2)] for a, b in merged]
    params["edit"] = {"segments": edit_lines, "speakers": speakers or None, "fx": fx,
                      "source_language": project.get("source_language"),
                      "cuts": project.get("cuts", []), "voice_model": project.get("voice_model"),
                      "tts_model": project.get("tts_model")}
    new_id = uuid.uuid4().hex[:12]
    with Session() as s:
        s.add(Job(id=new_id, user_id=user.id, status="queued", params=params, data={},
                  input_key=job.input_key, logo_key=job.logo_key, charged_seconds=0.0))
        s.commit()
    jobs_queue.enqueue(new_id)
    return {"job_id": new_id}


class PreviewBody(BaseModel):
    id: int | None = None                  # project line (its emotion direction is used, so Apply reuses the clip)
    text: str = Field(max_length=800)
    voice: str = Field(max_length=40)      # voice name to hear it in (e.g. the voice of the character you picked)


_preview_times: dict[int, list[float]] = {}


@app.post("/api/jobs/{job_id}/preview-line")
def preview_line(job_id: str, body: PreviewBody, user: User = Depends(auth.current_user)):
    """Hear ONE line in a chosen voice before pressing Apply: one TTS request, cached for the render."""
    if not looks.valid(body.voice):
        raise HTTPException(status_code=400, detail=f"Unknown voice: {body.voice}")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="This line has no text.")
    now = time.time()
    recent = [t for t in _preview_times.get(user.id, []) if now - t < 60]
    if len(recent) >= 12:
        raise HTTPException(status_code=429, detail="Too many previews. Wait a moment.")
    _preview_times[user.id] = recent + [now]
    with Session() as s:
        job = s.get(Job, job_id)
    project = ((job.data or {}).get("result") or {}).get("project") if job and job.user_id == user.id else None
    if not project:
        raise HTTPException(status_code=404, detail="Unknown job")
    _refuse_if_voice_limit()
    src = next((sg for sg in project["segments"] if sg["id"] == body.id), None) if body.id is not None else None
    import pipeline
    try:
        path = pipeline.preview_line(body.text.strip(), body.voice, (src or {}).get("style"),
                                     project.get("voice_model") or {}, project.get("tts_model"), (job.params or {}).get("voice_quality"))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Voice preview failed: {str(exc)[:160]}")
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
