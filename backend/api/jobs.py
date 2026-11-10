"""Job routes: upload, poll status, cancel, re-render, preview one line.
Split out of main.py; nothing here changed behaviour, only location.

A few names below (MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, upload_duration, lock_admission) are imported as plain
module-level names and referenced as bare names inside the route functions on purpose, rather than passed around or
re-imported elsewhere: several tests override them with `api.jobs.NAME = ...` to exercise a tight limit or a fake
upload duration, and Python resolves a bare name from the function's OWN defining module at call time -- so keeping
them here, read directly, is what makes that still work after the split."""
import json
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from db import Job, Session, User, active_jobs, lock_admission
from config import FILE_TTL_HOURS, LOGOS_DIR, MAX_ACTIVE_JOBS_PER_USER, MAX_UPLOAD_MB, MAX_VIDEO_MINUTES, SIGNED_URL_SECONDS, UPLOAD_DIR
from common import tts_provider, upload_duration
from services.quota import check_limits, clean_blurs, job_view, refuse_if_voice_limit
import auth
import capacity
import edit_limits
import jobs_queue
import looks
import safe_media
import storage
from admin import settings as runtime_settings
from voices import VOICE_NAMES

router = APIRouter(prefix="/api", tags=["jobs"])


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


def _refuse_if_voice_limit():
    refuse_if_voice_limit(tts_provider)


@router.post("/jobs")
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
              "logo_x": logo_x, "logo_y": logo_y, "manual_blurs": clean_blurs(manual_blurs),
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
                check_limits(s, user, seconds, MAX_ACTIVE_JOBS_PER_USER)
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


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(auth.current_user)):
    with Session() as s:
        job = s.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job_view(job, SIGNED_URL_SECONDS, FILE_TTL_HOURS)


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


@router.post("/jobs/{job_id}/rerender")
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


@router.post("/jobs/{job_id}/preview-line")
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


@router.post("/jobs/{job_id}/cancel")
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
