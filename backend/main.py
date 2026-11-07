from config import (ALLOW_SIGNUP, CORS_ORIGINS, DEFAULT_DAILY_MINUTES, FILE_TTL_HOURS, GLOBAL_DAILY_MINUTES,
                    LOGOS_DIR, MAINTENANCE_MODE, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES,
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
from sqlalchemy import func, select

import auth
import jobs_queue
import storage
from common import media_duration, tts_provider
from db import Job, Session, User, active_jobs, used_seconds_today
from voices import VOICES, VOICE_NAMES

import logging


class _QuietPolling(logging.Filter):
    """The page polls /api/jobs/<id> every 1.5 s; those lines bury everything useful in the terminal."""
    def filter(self, record):
        msg = record.getMessage()
        return not ("GET /api/jobs/" in msg and '" 200' in msg)


logging.getLogger("uvicorn.access").addFilter(_QuietPolling())

app = FastAPI(title="RedNote Video Recap Backend", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,  # bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.on_event("startup")
def _startup():
    _fail_orphaned_jobs()
    if storage.BACKEND == "local":
        threading.Thread(target=_cleanup_loop, daemon=True).start()


@app.get("/")
def read_root():
    return {"message": "RedNote Recap API", "version": app.version}


@app.get("/health")
def health():
    return {"ok": True}


# ---------- accounts ----------

class Credentials(BaseModel):
    email: str
    password: str


def _quota(user: User) -> dict:
    with Session() as s:
        used = used_seconds_today(s, user.id)
    limit = user.daily_minutes * 60
    return {"daily_minutes": user.daily_minutes, "used_seconds": round(used), "remaining_seconds": max(0, round(limit - used))}


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
        s.commit()
    return {"token": auth.make_token(user), "email": email, **_quota(user)}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    auth.rate_limit(request)
    with Session() as s:
        user = s.execute(select(User).where(User.email == body.email.strip().lower())).scalar_one_or_none()
    if not user or not user.is_active or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password.")
    return {"token": auth.make_token(user), "email": user.email, **_quota(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(auth.current_user)):
    return {"email": user.email, **_quota(user)}


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
    return FileResponse(path, media_type="audio/wav", filename=f"{name}-sample.wav")


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
    # effects
    blur_subtitles: bool = Form(True),
    enable_subtitles: bool = Form(True),
    remove_watermark: bool = Form(True),
    enable_flip: bool = Form(True),
    flip_vertical: bool = Form(False),
    video_speed: float = Form(1.0),
    brightness: float = Form(0.0),
    contrast: float = Form(1.0),
    saturation: float = Form(1.0),
    logo_position: str = Form("top-right"),
    logo_size: float = Form(0.15),
):
    if MAINTENANCE_MODE:
        raise HTTPException(status_code=503, detail="We're temporarily not accepting new videos. Please try again later.")
    if not video_file:
        raise HTTPException(status_code=400, detail="No video file provided.")
    _refuse_if_voice_limit()
    if tts_provider() == "gemini" and voice_type != "su" and voice_type not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice_type}")
    if tts_provider() == "elevenlabs" and voice_type != "su":
        raise HTTPException(status_code=400, detail=f"Unsupported voice selection: {voice_type}")
    params = {"voice_type": voice_type, "target_language": target_language,
              "allow_voice_speedup": allow_voice_speedup, "max_voice_speedup": max_voice_speedup,
              "min_video_speed": min_video_speed, "fit_translation": fit_translation,
              "keep_background": keep_background, "blur_subtitles": blur_subtitles,
              "enable_subtitles": enable_subtitles, "remove_watermark": remove_watermark,
              "enable_flip": enable_flip, "flip_vertical": flip_vertical, "video_speed": video_speed,
              "brightness": brightness, "contrast": contrast, "saturation": saturation,
              "logo_position": logo_position, "logo_size": logo_size}

    with Session() as s:
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
            used = used_seconds_today(s, user.id)
            if used + seconds > user.daily_minutes * 60:
                left = max(0, user.daily_minutes * 60 - used)
                raise HTTPException(status_code=402, detail=(
                    f"Daily limit reached: {left / 60:.1f} of your {user.daily_minutes} minutes left today, "
                    f"this video is {seconds / 60:.1f} minutes."))
            if GLOBAL_DAILY_MINUTES and used_seconds_today(s) + seconds > GLOBAL_DAILY_MINUTES * 60:
                raise HTTPException(status_code=503, detail="We've reached today's capacity. Please try again tomorrow.")
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


def _job_view(job: Job) -> dict:
    view = {"id": job.id, "status": job.status, "stage": job.stage, "progress": job.progress,
            "error": job.error, **{k: v for k, v in (job.data or {}).items() if k not in ("result", "started_at", "run_seconds")}}
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
    start: float = Field(ge=0)                       # source-video time where this line's scene begins
    text: str = Field(max_length=800)
    source_text: str = Field("", max_length=2000)
    tempo: float | None = Field(None, ge=0.7, le=1.6)  # fixed voice speed for this line (None = automatic)


class RerenderBody(BaseModel):
    segments: list[EditLine] = Field(min_length=1, max_length=600)
    voice_type: str | None = None


@app.post("/api/jobs/{job_id}/rerender")
def rerender(job_id: str, body: RerenderBody, user: User = Depends(auth.current_user)):
    """New job from a finished one: same source video and settings, edited lines. Unchanged lines reuse their
    cached voice clips, so only edited lines cost a TTS request."""
    if MAINTENANCE_MODE:
        raise HTTPException(status_code=503, detail="We're temporarily not accepting new work. Please try again later.")
    with Session() as s:
        job = s.get(Job, job_id)
        if job is None or job.user_id != user.id:
            raise HTTPException(status_code=404, detail="Unknown job")
        if active_jobs(s, user.id) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(status_code=429, detail="You already have videos processing. Wait for one to finish.")
    project = ((job.data or {}).get("result") or {}).get("project")
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
    params["edit"] = {"segments": [l.model_dump() for l in lines], "fx": project["fx"],
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
