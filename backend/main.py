from dotenv import load_dotenv
load_dotenv()  # reads backend/.env before anything reads the environment

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import subprocess
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
import mimetypes
import requests
from recap_engine import (BREATH, EffectOptions, SyncOptions, plan_timeline, probe_video, render, write_srt)
from subtitle_detect import detect_text_regions, to_pixels
from audio_tools import cleanup_separation, separate_background
from fit_text import available as fit_available, shorten
import gemini_tts
import gemini_dub
import local_dub
from voices import VOICES, VOICE_NAMES
from contextlib import contextmanager
from datetime import datetime, timezone

app = FastAPI(title="RedNote Video Recap Backend", version="2.6.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
LOGOS_DIR = "uploads/logos"
OUTPUT_DIR = "outputs"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOGOS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


class ElevenLabsRateLimited(RuntimeError):
    pass


@contextmanager
def pipeline_stage(name: str):
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] [{name}] START", flush=True)
    try:
        yield
    except Exception as exc:
        elapsed = time.monotonic() - started
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(
            f"[{timestamp}] [{name}] FAILED after {elapsed:.2f}s: {exc}",
            flush=True,
        )
        raise
    else:
        elapsed = time.monotonic() - started
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{timestamp}] [{name}] DONE in {elapsed:.2f}s", flush=True)


def elevenlabs_dub(video_path: str, target_language: str) -> tuple[str | None, list[dict]]:
    """Use ElevenLabs Dubbing v2 to transcribe, translate, and return timed text segments."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set in the FastAPI server environment.")

    api_base = "https://api.elevenlabs.io/v1/dubbing"
    headers = {"xi-api-key": api_key}
    timeout_seconds = int(os.getenv("ELEVENLABS_DUBBING_TIMEOUT_SECONDS", "900"))
    deadline = time.monotonic() + timeout_seconds

    with pipeline_stage("ElevenLabs Dubbing Project"):
        with open(video_path, "rb") as source_file:
            response = requests.post(
                f"{api_base}/project",
                headers=headers,
                data={"model_id": "dubbing_v2", "target_language": target_language},
                files={
                    "file": (
                        os.path.basename(video_path),
                        source_file,
                        mimetypes.guess_type(video_path)[0] or "application/octet-stream",
                    )
                },
                timeout=(15, 180),
            )
        if response.status_code == 429:
            raise ElevenLabsRateLimited("ElevenLabs rate-limited this dubbing request (HTTP 429).")
        response.raise_for_status()
        project = response.json()

    project_id = project["project_id"]
    language_ids = project.get("language_ids") or []
    language_id = language_ids[0] if language_ids else None

    with pipeline_stage("ElevenLabs Dubbing Preparation"):
        while time.monotonic() < deadline:
            if project.get("status") == "failed":
                raise RuntimeError(f"ElevenLabs could not prepare the source: {project.get('error')}")
            if project.get("status") == "ready":
                break
            time.sleep(2)
            response = requests.get(
                f"{api_base}/project/{project_id}", headers=headers, timeout=(10, 30)
            )
            response.raise_for_status()
            project = response.json()
            language_ids = project.get("language_ids") or language_ids
            if not language_id and language_ids:
                language_id = language_ids[0]
        else:
            raise TimeoutError(f"ElevenLabs source preparation exceeded {timeout_seconds} seconds.")

    if not language_id:
        raise RuntimeError("ElevenLabs project became ready without a Burmese language target.")

    with pipeline_stage("ElevenLabs Burmese Dubbing"):
        while time.monotonic() < deadline:
            response = requests.get(
                f"{api_base}/project/{project_id}/language/{language_id}",
                headers=headers,
                timeout=(10, 30),
            )
            response.raise_for_status()
            language_target = response.json()
            status = language_target.get("status")
            if status == "failed":
                raise RuntimeError(f"ElevenLabs dubbing failed: {language_target.get('error')}")
            if status == "completed":
                break
            time.sleep(2)
        else:
            raise TimeoutError(f"ElevenLabs dubbing exceeded {timeout_seconds} seconds.")

    with pipeline_stage("ElevenLabs Timed Transcript"):
        response = requests.get(
            f"{api_base}/project/{project_id}/language/{language_id}/transcript",
            headers=headers,
            timeout=(10, 30),
        )
        response.raise_for_status()
        transcript = response.json()
        segments = [
            {
                "start": float(segment["start_s"]),
                "end": float(segment["end_s"]),
                "source_text": segment.get("source_text", ""),
                "translated_text": segment.get("translation", ""),
            }
            for segment in transcript.get("segments", [])
            if segment.get("translation") and segment.get("end_s", 0) > segment.get("start_s", 0)
        ]

    if not segments:
        raise RuntimeError("ElevenLabs returned no translated timed transcript segments.")

    with pipeline_stage("ElevenLabs Burmese Transcript"):
        for segment in segments:
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            print(
                f"[{timestamp}] [Burmese {segment['start']:.2f}s–{segment['end']:.2f}s] "
                f"{segment['translated_text']}",
                flush=True,
            )
    return project.get("source_language") or transcript.get("source_language"), segments

def media_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=True,
    )
    return float(result.stdout.strip())


def save_upload(upload: UploadFile, directory: str) -> str:
    """Store an upload under a unique name so concurrent jobs never overwrite each other."""
    ext = os.path.splitext(os.path.basename(upload.filename or ""))[1][:10]
    path = os.path.join(directory, f"{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as buffer:
        shutil.copyfileobj(upload.file, buffer)
    return path


# ---------- job queue ----------

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("RECAP_WORKERS", "2")))


def set_job(job_id: str, **fields):
    with JOBS_LOCK:
        JOBS[job_id].update(fields)


def tts_provider() -> str:
    """TTS_PROVIDER=gemini|elevenlabs; default is Gemini when a Google key is present."""
    choice = os.getenv("TTS_PROVIDER", "").lower()
    if choice in ("gemini", "elevenlabs"):
        return choice
    return "gemini" if gemini_tts.available() else "elevenlabs"


def dub_provider() -> str:
    """DUB_PROVIDER=local|elevenlabs|gemini; default is local (faster-whisper + NLLB, no API)."""
    choice = os.getenv("DUB_PROVIDER", "local").lower()
    return choice if choice in ("local", "elevenlabs", "gemini") else "local"


def audio_ext() -> str:
    return ".wav" if tts_provider() == "gemini" else ".mp3"


def synthesize(text: str, voice: str, path: str):
    if tts_provider() == "gemini":
        # "su" is the UI's default Burmese voice slot; map it to the configured Gemini voice.
        gemini_tts.synthesize_to_file(text, path, None if voice == "su" else voice)
        return media_duration(path)
    response = requests.post(
        os.getenv("ELEVENLABS_TTS_URL", "http://127.0.0.1:8001/api/tts"),
        json={"text": text, "voice": voice},
        timeout=(5, 180),
    )
    if response.status_code >= 400:
        try:
            body = response.json()
            reason = f"{body.get('upstreamStatus', '')} {body.get('detail') or body.get('error')}".strip()
        except ValueError:
            reason = response.text[:300]
        raise RuntimeError(f"Voice-over failed ({response.status_code}): {reason}")
    if not response.headers.get("content-type", "").startswith("audio/"):
        raise RuntimeError("ElevenLabs TTS endpoint returned a non-audio response.")
    with open(path, "wb") as audio_file:
        audio_file.write(response.content)
    return media_duration(path)


def fit_segments_to_slots(segments, video_duration, job, voice, target_language, temp_paths, max_rounds=2):
    """Re-write lines whose voice-over overshoots their scene so the video rarely has to slow down."""
    for i, segment in enumerate(segments):
        end = segments[i + 1]["start"] if i + 1 < len(segments) else video_duration
        budget = max(end - segment["start"] - BREATH, 0.4)
        for round_no in range(max_rounds):
            if segment["audio_dur"] <= budget * 1.05:
                break
            try:
                new_text = shorten(segment["source_text"], segment["translated_text"], target_language,
                                   segment["audio_dur"], budget)
                root, ext = os.path.splitext(segment["audio_path"])
                new_path = f"{root}_fit{round_no}{ext}"
                temp_paths.append(new_path)
                new_dur = synthesize(new_text, voice, new_path)
            except Exception as exc:  # fitting is best-effort; the engine still syncs by slowing video
                print(f"  fit skipped for segment {i + 1}: {exc}", flush=True)
                break
            if new_dur >= segment["audio_dur"]:
                break
            print(f"  fit {i + 1}: {segment['audio_dur']:.1f}s -> {new_dur:.1f}s (budget {budget:.1f}s)", flush=True)
            segment.update(translated_text=new_text, audio_path=new_path, audio_dur=new_dur)


def run_job(job_id: str, video_path: str, logo_path: str | None, p: dict):
    output_filename = f"recap_output_{job_id}.mp4"
    srt_filename = f"recap_output_{job_id}.srt"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    temp_paths: list[str] = []
    bg_state: dict = {}
    bg_thread = None
    try:
        info = probe_video(video_path)
        video_duration = media_duration(video_path)
        fx_kwargs = {}

        # 1. Where are the source subtitles / watermarks? Only those regions get blurred.
        if p["blur_subtitles"] or p["remove_watermark"]:
            set_job(job_id, stage="Detecting subtitles", progress=3)
            with pipeline_stage("Subtitle Detection"):
                try:
                    found = detect_text_regions(video_path, video_duration)
                    if found["subtitle"]:
                        fx_kwargs["subtitle_rect"] = to_pixels(found["subtitle"], info["width"], info["height"])
                    fx_kwargs["watermark_rects"] = [
                        to_pixels(r, info["width"], info["height"], 0.01, 0.005) for r in found["watermarks"]
                    ]
                    print(f"  subtitles: {found['subtitle']}  watermarks: {len(found['watermarks'])}", flush=True)
                except Exception as exc:  # OCR unavailable: fall back to the classic lower-third strip
                    print(f"  detection failed ({exc}); using fixed lower-third", flush=True)
                    fx_kwargs["subtitle_rect"] = (0, int(info["height"] * 0.72) // 2 * 2,
                                                  info["width"] // 2 * 2, int(info["height"] * 0.25) // 2 * 2)
        set_job(job_id, subtitles_detected=bool(fx_kwargs.get("subtitle_rect")))

        # 2. Keep the original music/effects (voice removed) — runs alongside dubbing.
        if p["keep_background"]:
            def _separate():
                try:
                    bg_state["path"] = separate_background(video_path, OUTPUT_DIR, job_id)
                except Exception as exc:
                    bg_state["error"] = str(exc)
            bg_thread = threading.Thread(target=_separate, daemon=True)
            bg_thread.start()

        # 3. Transcribe + translate.
        set_job(job_id, stage="Transcribing and translating", progress=10)
        with pipeline_stage("Transcribe + Translate"):
            primary = dub_provider()
            runners = {
                "local": lambda: local_dub.dub(video_path, p["target_language"]),
                "elevenlabs": lambda: elevenlabs_dub(video_path, p["target_language"]),
                "gemini": lambda: gemini_dub.dub(video_path, p["target_language"], retries=2),
            }
            order = [primary] + [n for n in runners if n != primary]
            if not os.getenv("ELEVENLABS_API_KEY"):
                order = [n for n in order if n != "elevenlabs"]
            for i, name in enumerate(order):
                try:
                    detected_source_language, segments = runners[name]()
                    break
                except Exception as exc:
                    if i == len(order) - 1:
                        raise
                    print(f"  {name} transcribe/translate failed ({exc}); trying {order[i + 1]}", flush=True)
        segments.sort(key=lambda s: s["start"])

        # 4. Voice-over.
        with pipeline_stage(f"Voiceover ({tts_provider()})"):
            for index, segment in enumerate(segments, start=1):
                set_job(job_id, stage=f"Voice-over {index}/{len(segments)}",
                        progress=35 + int(25 * (index - 1) / len(segments)))
                segment_path = os.path.join(OUTPUT_DIR, f"voice_{job_id}_{index}{audio_ext()}")
                temp_paths.append(segment_path)
                segment["audio_path"] = segment_path
                segment["audio_dur"] = synthesize(segment["translated_text"], p["voice_type"], segment_path)

        # 5. Make each line fit its scene.
        if p["fit_translation"] and fit_available():
            set_job(job_id, stage="Fitting translation to scene timing", progress=62)
            with pipeline_stage("Fit Translation To Timing"):
                fit_segments_to_slots(segments, video_duration, job_id, p["voice_type"], p["target_language"], temp_paths)

        # 6. Sync timeline + render.
        set_job(job_id, stage="Building sync timeline", progress=68)
        scenes = plan_timeline(
            segments,
            video_duration,
            SyncOptions(
                allow_speedup=p["allow_voice_speedup"],
                max_speedup=min(max(p["max_voice_speedup"], 1.0), 1.5),
                min_video_speed=min(max(p["min_video_speed"], 0.5), 1.0),
            ),
        )
        for scene in scenes:
            if scene.audio_index is not None:
                print(f"  src {scene.src_start:.2f}-{scene.src_end:.2f}s -> out {scene.out_start:.2f}s "
                      f"+{scene.out_len:.2f}s [{scene.action}]", flush=True)

        if bg_thread:
            set_job(job_id, stage="Separating background music", progress=70)
            bg_thread.join()
            if "error" in bg_state:
                print(f"  background separation failed: {bg_state['error']}", flush=True)

        effects = EffectOptions(
            blur_subtitles=p["blur_subtitles"],
            blur_watermark=p["remove_watermark"],
            flip_h=p["enable_flip"],
            flip_v=p["flip_vertical"],
            speed=p["video_speed"],
            brightness=min(max(p["brightness"], -1.0), 1.0),
            contrast=min(max(p["contrast"], 0.0), 2.0),
            saturation=min(max(p["saturation"], 0.0), 3.0),
            logo_path=logo_path,
            logo_width_frac=min(max(p["logo_size"], 0.05), 0.5),
            logo_position=p["logo_position"],
            captions=p["enable_subtitles"],
            background_path=bg_state.get("path"),
            **fx_kwargs,
        )
        set_job(job_id, stage="Rendering video", progress=75)
        with pipeline_stage("FFmpeg Render"):
            result = render(video_path, segments, scenes, effects, output_path, OUTPUT_DIR, job_id)
        write_srt(result["cues"], os.path.join(OUTPUT_DIR, srt_filename))

        set_job(
            job_id,
            status="done",
            stage="Done",
            progress=100,
            result={
                "source_language": detected_source_language,
                "target_language": p["target_language"],
                "source_duration": video_duration,
                "output_duration": result["duration"],
                "subtitles_detected": bool(fx_kwargs.get("subtitle_rect")),
                "background_kept": "path" in bg_state,
                "transcript": " ".join(s["translated_text"] for s in segments),
                "timeline": [
                    {"source_start": sc.src_start, "source_end": sc.src_end, "output_start": sc.out_start,
                     "output_length": sc.out_len, "action": sc.action, "text": sc.text}
                    for sc in scenes
                ],
                "video_url": f"/api/preview/{output_filename}",
                "download_url": f"/api/download/{output_filename}",
                "subtitle_url": f"/api/download/{srt_filename}",
            },
        )
    except ElevenLabsRateLimited:
        set_job(job_id, status="error", error="ElevenLabs rate-limited this dubbing request. Please retry later.")
    except Exception as exc:
        print(f"[job {job_id}] FAILED: {exc}", flush=True)
        set_job(job_id, status="error", error=f"Recap generation failed: {exc}")
    finally:
        if bg_thread:
            bg_thread.join(timeout=5)
            cleanup_separation(OUTPUT_DIR, job_id)
        for temp_path in temp_paths:
            if os.path.exists(temp_path):
                os.remove(temp_path)


SAMPLES_DIR = "voice_samples"


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


@app.get("/")
def read_root():
    return {"message": "RedNote Recap Backend is running with Gemini dubbing + TTS (ElevenLabs optional)."}


@app.post("/api/jobs")
async def create_job(
    video_file: UploadFile = File(None),
    custom_logo: UploadFile = File(None),
    voice_type: str = Form("su"),
    target_language: str = Form("my"),
    # sync policy
    allow_voice_speedup: bool = Form(True),
    max_voice_speedup: float = Form(1.2),
    min_video_speed: float = Form(0.85),
    fit_translation: bool = Form(False),
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
    if not video_file:
        raise HTTPException(status_code=400, detail="No video file provided.")
    if tts_provider() == "gemini" and voice_type != "su" and voice_type not in VOICE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown voice: {voice_type}")
    if tts_provider() == "elevenlabs" and voice_type != "su":
        raise HTTPException(status_code=400, detail=f"Unsupported voice selection: {voice_type}")
    params = {k: v for k, v in locals().items() if k not in ("video_file", "custom_logo")}
    video_path = save_upload(video_file, UPLOAD_DIR)
    logo_path = save_upload(custom_logo, LOGOS_DIR) if custom_logo else None

    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"id": job_id, "status": "running", "stage": "Queued", "progress": 0}
    EXECUTOR.submit(run_job, job_id, video_path, logo_path, params)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Unknown job")
        return dict(job)


def _output_file(filename: str) -> str:
    file_path = os.path.join(OUTPUT_DIR, os.path.basename(filename))
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return file_path


@app.get("/api/preview/{filename}")
def preview_file(filename: str):
    return FileResponse(_output_file(filename), media_type="video/mp4")


@app.get("/api/download/{filename}")
def download_file(filename: str):
    file_path = _output_file(filename)
    media_type = "application/x-subrip" if file_path.endswith(".srt") else "video/mp4"
    return FileResponse(file_path, media_type=media_type, filename=os.path.basename(file_path))
