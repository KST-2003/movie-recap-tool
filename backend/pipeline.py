"""The dubbing pipeline. Runs inside a queue worker (or an in-process thread in dev), never inside a request."""
import mimetypes
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

import requests

import gemini_dub
import gemini_tts
import local_dub
import storage
from common import audio_ext, dub_provider, media_duration, tts_provider
from audio_tools import cleanup_separation, separate_background
from config import LOGOS_DIR, OUTPUT_DIR, UPLOAD_DIR
from db import Job, Session, update_job
from fit_text import available as fit_available, shorten
from recap_engine import (BREATH, EffectOptions, SyncOptions, plan_timeline, probe_video, render, write_srt)
from subtitle_detect import detect_text_regions, to_pixels


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

TTS_WORKERS = int(os.getenv("TTS_WORKERS", "8"))


def set_job(job_id: str, **fields):
    update_job(job_id, **fields)


def synthesize(text: str, voice: str, path: str):
    if tts_provider() == "fake":  # no API: a tone about as long as speech would be (for tests / load tests)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"sine=frequency=220:duration={max(0.8, len(text) / 12):.2f}", "-ar", "24000", path], check=True)
        return media_duration(path)
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


def fit_segments_to_slots(segments, video_duration, job, voice, target_language, temp_paths,
                          max_rounds=2, tolerance=1.05):
    """Re-write lines whose voice-over overshoots their scene (even after the allowed speed-up),
    so the video rarely has to slow down or freeze. Lines are fixed in parallel."""
    def fit_one(i):
        segment = segments[i]
        end = segments[i + 1]["start"] if i + 1 < len(segments) else video_duration
        budget = max(end - segment["start"] - BREATH, 0.4)
        for round_no in range(max_rounds):
            if segment["audio_dur"] <= budget * tolerance:
                break
            try:
                new_text = shorten(segment["source_text"], segment["translated_text"], target_language,
                                   segment["audio_dur"], budget * tolerance)
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

    with ThreadPoolExecutor(max_workers=TTS_WORKERS) as pool:
        list(pool.map(fit_one, range(len(segments))))


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
            order = [primary] + [n for n in ("elevenlabs", "gemini", "local") if n != primary]  # local last: slow, weakest Burmese
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
            if tts_provider() == "gemini":
                gemini_tts._get_client()  # create the shared client before worker threads start
            done = [0]

            def _voice(item):
                index, segment = item
                segment_path = os.path.join(OUTPUT_DIR, f"voice_{job_id}_{index}{audio_ext()}")
                temp_paths.append(segment_path)
                segment["audio_path"] = segment_path
                segment["audio_dur"] = synthesize(segment["translated_text"], p["voice_type"], segment_path)
                done[0] += 1
                set_job(job_id, stage=f"Voice-over {done[0]}/{len(segments)}",
                        progress=35 + int(25 * done[0] / len(segments)))

            with ThreadPoolExecutor(max_workers=TTS_WORKERS) as pool:
                list(pool.map(_voice, enumerate(segments, start=1)))

        # 5. Make each line fit its scene.
        if p["fit_translation"] and fit_available():
            set_job(job_id, stage="Fitting translation to scene timing", progress=62)
            with pipeline_stage("Fit Translation To Timing"):
                fit_segments_to_slots(
                    segments, video_duration, job_id, p["voice_type"], p["target_language"], temp_paths,
                    tolerance=(max(p["max_voice_speedup"], 1.0) if p["allow_voice_speedup"] else 1.05) * 1.02)

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
        srt_path = os.path.join(OUTPUT_DIR, srt_filename)
        write_srt(result["cues"], srt_path)
        video_key = storage.put_output(output_path)  # s3: uploads and removes the local copy
        srt_key = storage.put_output(srt_path)

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
                "video_file": video_key,   # the API turns these into signed URLs when the client asks
                "subtitle_file": srt_key,
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





def run_job_by_id(job_id: str):
    """Queue entry point: load the job from the database, fetch its files, run, clean up."""
    with Session() as sess:
        job = sess.get(Job, job_id)
        if job is None:
            return
        params, input_key, logo_key = dict(job.params or {}), job.input_key, job.logo_key
    set_job(job_id, status="running", stage="Starting", progress=1)
    video_path = logo_path = None
    try:
        video_path = storage.fetch(input_key)
        logo_path = storage.fetch(logo_key, LOGOS_DIR) if logo_key else None
        run_job(job_id, video_path, logo_path, params)
    except Exception as exc:  # e.g. the upload could not be fetched
        print(f"[job {job_id}] FAILED before start: {exc}", flush=True)
        set_job(job_id, status="error", error=f"Recap generation failed: {exc}")
    finally:
        # The source upload is no longer needed once the job ends.
        for path in (video_path, logo_path):
            storage.delete_local(path)
        if storage.BACKEND == "s3":
            for key in (input_key, logo_key):
                if key:
                    try:
                        storage._client().delete_object(Bucket=storage.BUCKET, Key=key)
                    except Exception:
                        pass
