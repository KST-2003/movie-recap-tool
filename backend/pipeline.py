"""The dubbing pipeline. Runs inside a queue worker (or an in-process thread in dev), never inside a request."""
import hashlib
import mimetypes
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone

import requests

import bulk_tts
import duration_model
import gemini_dub
import gemini_tts
import local_dub
import storage
from common import audio_ext, dub_provider, media_duration, tts_provider
from audio_tools import cleanup_separation, separate_background
from config import LOGOS_DIR, OUTPUT_DIR, UPLOAD_DIR
from db import Job, Session, update_job
import fit_text
from fit_text import available as fit_available
from scene_cuts import detect_cuts
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
TTS_BULK = os.getenv("TTS_BULK", "1").lower() in ("1", "true")  # several sentences per TTS request; set TTS_BULK=0 to turn off


def clip_name(text: str, voice: str) -> str:
    """Cache name of a voice clip: same text + voice = same clip, so an edit only re-voices changed lines."""
    return hashlib.sha1(f"{voice}|{text}".encode()).hexdigest() + audio_ext()


class JobCancelled(Exception):
    """The user pressed Cancel: stop quietly (nothing is saved, nothing is charged)."""


def set_job(job_id: str, **fields):
    if not update_job(job_id, **fields):
        raise JobCancelled(job_id)


JOB_HARD_LIMIT = float(os.getenv("JOB_HARD_LIMIT_SECONDS", "720"))   # a job that runs longer than this fails cleanly
_job_started: dict[str, float] = {}


def check_cancelled(job_id: str):
    """Cheap DB look so long loops stop spending TTS/CPU after Cancel (or once the hard time limit has passed)."""
    started = _job_started.get(job_id)
    if started and time.time() - started > JOB_HARD_LIMIT:
        raise RuntimeError(f"This video took longer than {JOB_HARD_LIMIT / 60:.0f} minutes (Gemini was slow or busy). "
                           "Please try again; nothing was charged.")
    with Session() as sess:
        job = sess.get(Job, job_id)
        if job is not None and job.status == "cancelled":
            raise JobCancelled(job_id)


def synthesize(text: str, voice: str, path: str):
    if tts_provider() == "fake":  # no API: tones about as long as speech would be (tests / load tests)
        parts = [t for t in text.split("\n\n") if t.strip()] or [text]
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for t in parts:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=220:duration={max(0.8, duration_model.predict(t)):.2f}"]
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=0.5"] if t is not parts[-1] else []
        n_in = len(parts) * 2 - 1
        fc = "".join(f"[{i}:a]aresample=24000,aformat=channel_layouts=mono[a{i}];" for i in range(n_in))
        fc += "".join(f"[a{i}]" for i in range(n_in)) + f"concat=n={n_in}:v=0:a=1[out]"
        subprocess.run(cmd + ["-filter_complex", fc, "-map", "[out]", path], check=True)
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


FIT_FILL = float(os.getenv("FIT_FILL_RATIO", "0.85"))   # a voice shorter than this share of the original speech gets lengthened
FIT_MIN_GAP = float(os.getenv("FIT_MIN_GAP_SECONDS", "0.5"))  # ...but only if that leaves at least this much dead air
FIT_ROUNDS = int(os.getenv("FIT_ROUNDS", "2"))
# Time budget: a video must be finished in about its own length (hard cap JOB_BUDGET_MAX seconds). The optional
# polishing steps (pre-fit, fit rounds) only start if enough budget is left AFTER reserving time for the render.
JOB_BUDGET_MAX = float(os.getenv("JOB_BUDGET_MAX_SECONDS", "540"))
RENDER_SECONDS_PER_VIDEO_SECOND = float(os.getenv("RENDER_SECONDS_PER_VIDEO_SECOND", "0.2"))   # measured 0.14 on an M2 Air


def voice_many(texts: list[str], paths: list[str], voice: str, model: dict, job_id: str, progress=None) -> list[float]:
    """Voice many lines with as few requests as possible (several lines per request when TTS_BULK is on; a group
    whose audio can't be split reliably is retried as two smaller groups, then line by line). Returns the durations."""
    durs = [0.0] * len(texts)

    def single(i: int):
        check_cancelled(job_id)
        durs[i] = synthesize(texts[i], voice, paths[i])
        storage.put_clip(paths[i], clip_name(texts[i], voice))
        if progress:
            progress(1)

    def group(idx: list[int]):
        check_cancelled(job_id)
        if len(idx) > 1:
            try:
                ok = bulk_tts.synthesize_batch([texts[i] for i in idx], voice, [paths[i] for i in idx],
                                               lambda text, path: synthesize(text, voice, path), OUTPUT_DIR, model)
                if ok:
                    for i in idx:
                        durs[i] = media_duration(paths[i])
                        storage.put_clip(paths[i], clip_name(texts[i], voice))
                    if progress:
                        progress(len(idx))
                    return
                print(f"  bulk voice split not trusted for {len(idx)} lines; trying two smaller groups", flush=True)
                half = len(idx) // 2
                group(idx[:half])
                group(idx[half:])
                return
            except JobCancelled:
                raise
            except Exception as exc:
                print(f"  bulk voice failed ({exc}); using one request each", flush=True)
        for i in idx:
            single(i)

    batches = bulk_tts.make_batches(texts) if TTS_BULK else [[i] for i in range(len(texts))]
    with ThreadPoolExecutor(max_workers=TTS_WORKERS) as pool:
        list(pool.map(group, batches))
    return durs


def _slot_bounds(segments, i, video_duration):
    sg = segments[i]
    nxt = segments[i + 1]["start"] if i + 1 < len(segments) else video_duration
    slot = max(nxt - sg["start"], 0.4)
    speech = min(sg["end"] - sg["start"], slot) if sg.get("end") else slot
    return max(slot - BREATH, 0.4), max(speech - BREATH, 0.4)   # (must not run into next line, as long as the speaker)


def _plan(dur, upper, want, lengthen=True):
    if dur > upper * 1.05:
        return "shorten", upper * 0.95
    if lengthen and dur < want * FIT_FILL and want - dur >= FIT_MIN_GAP:
        return "lengthen", want
    return None


def _rewrite_lines(segments, todo, model, language, job_id, time_left=None):
    """todo: {index: (mode, target seconds)}. Asks the LLM for all of them in bulk (~20 lines per request) and checks
    every answer with the duration model; answers that miss the target are re-asked once (text only, no voice).
    Returns {index: new text}."""
    def target_chars(text, seconds):
        syll = max((seconds - model["b"]) / model["a"], 1.0)
        return max(4, int(syll * len(text) / max(duration_model.syllables(text), 1)))

    current = {i: segments[i]["translated_text"] for i in todo}
    pending = dict(todo)
    for _ask in range(2):
        items = [{"id": i, "source": segments[i].get("source_text", ""), "current": current[i], "mode": mode,
                  "target_chars": target_chars(current[i], tgt)} for i, (mode, tgt) in pending.items()]
        result = fit_text.rewrite_many(items, language)
        check_cancelled(job_id)
        pending = {}
        for i, (mode, tgt) in todo.items():
            new = result.get(i)
            if not new:
                continue
            current[i] = new
            pred = duration_model.predict(new, model)
            if abs(pred - tgt) > 0.15 * tgt:
                pending[i] = ("shorten" if pred > tgt else "lengthen", tgt)
        if not pending or (time_left and time_left() < 60):
            break
    return current


def prefit_segments(segments, video_duration, job_id, target_language, model, time_left=None):
    """BEFORE any voice is made: shorten lines the duration model predicts will overrun their scene. Most lines
    then need only one voice request instead of two. (Lengthening waits for real voice lengths: too risky to guess.)"""
    todo = {}
    for i, sg in enumerate(segments):
        upper, want = _slot_bounds(segments, i, video_duration)
        plan = _plan(duration_model.predict(sg["translated_text"], model), upper, want, lengthen=False)
        if plan:
            todo[i] = plan
    print(f"  pre-fit: {len(todo)} of {len(segments)} lines predicted too long for their scene", flush=True)
    if not todo:
        return
    if time_left and time_left() < 45:
        print("  pre-fit skipped: time budget", flush=True)
        return
    new = _rewrite_lines(segments, todo, model, target_language, job_id, time_left)
    kept = 0
    for i in todo:
        if new[i] != segments[i]["translated_text"] and duration_model.predict(new[i], model) < duration_model.predict(
                segments[i]["translated_text"], model):
            segments[i]["translated_text"] = new[i]
            kept += 1
    print(f"  pre-fit: {kept} lines shortened before voicing", flush=True)


def fit_segments_to_slots(segments, video_duration, job_id, voice, target_language, temp_paths, model, time_left=None):
    """AFTER voicing, with real lengths: make each voice line last about as long as the original speech of its scene,
    by rewriting the SCRIPT: too long -> shortened, too short -> lengthened with faithful detail (no dead air).
    Voice speed is only the last resort and is handled by the timeline. Dead air the SOURCE really has is kept.

    Built for speed: lines go to the LLM in bulk, each rewrite is checked with the duration model before any voice is
    paid for, and accepted rewrites are voiced together in batched TTS requests."""
    for round_no in range(FIT_ROUNDS):
        todo = {}
        for i in range(len(segments)):
            upper, want = _slot_bounds(segments, i, video_duration)
            plan = _plan(segments[i]["audio_dur"], upper, want)
            if plan:
                todo[i] = plan
        if not todo:
            break
        if time_left and time_left() < 75:  # a round needs roughly 20 s of LLM + 30 s of voice
            print(f"  fit round {round_no + 1} skipped: time budget (the timeline will speed up / slow down instead)", flush=True)
            break
        set_job(job_id, stage=f"Fitting lines to their scenes (round {round_no + 1}/{FIT_ROUNDS}): {len(todo)} lines",
                progress=62 + round_no * 3)
        print(f"  fit round {round_no + 1}: {len(todo)} of {len(segments)} lines need rewriting", flush=True)
        current = _rewrite_lines(segments, todo, model, target_language, job_id, time_left)
        voiced = []   # only voice rewrites the model expects to be an improvement
        for i, (mode, tgt) in todo.items():
            if current[i] == segments[i]["translated_text"]:
                continue
            pred = duration_model.predict(current[i], model)
            if (mode == "shorten" and pred < segments[i]["audio_dur"]) or (
                    mode == "lengthen" and pred > segments[i]["audio_dur"]):
                voiced.append(i)
        if not voiced:
            break
        paths = []
        for i in voiced:
            root, ext = os.path.splitext(segments[i]["audio_path"])
            path = f"{root}_fit{round_no}{ext}"
            temp_paths.append(path)
            paths.append(path)
        done = [0]

        def prog(n, total=len(voiced), r=round_no):
            done[0] += n
            set_job(job_id, stage=f"Voicing rewritten lines {done[0]}/{total}", progress=63 + r * 3)
        durs = voice_many([current[i] for i in voiced], paths, voice, model, job_id, prog)
        changed = 0
        for i, path, new_dur in zip(voiced, paths, durs):
            mode, _tgt = todo[i]
            upper, want = _slot_bounds(segments, i, video_duration)
            dur = segments[i]["audio_dur"]
            better = (new_dur < dur) if mode == "shorten" else (
                new_dur > dur and new_dur <= upper * 1.05 and abs(new_dur - want) < abs(dur - want))
            if better:
                segments[i].update(translated_text=current[i], audio_path=path, audio_dur=new_dur)
                changed += 1
        print(f"  fit round {round_no + 1}: {changed} of {len(voiced)} rewrites kept", flush=True)


def run_job(job_id: str, video_path: str, logo_path: str | None, p: dict):
    output_filename = f"recap_output_{job_id}.mp4"
    srt_filename = f"recap_output_{job_id}.srt"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    t0 = time.time()
    _job_started[job_id] = t0
    temp_paths: list[str] = []
    bg_state: dict = {}
    bg_thread = None
    try:
        info = probe_video(video_path)
        video_duration = media_duration(video_path)
        fx_kwargs = {}
        budget = min(max(video_duration * 0.9, 150.0), JOB_BUDGET_MAX)
        render_reserve = RENDER_SECONDS_PER_VIDEO_SECOND * video_duration + 20.0

        def time_left() -> float:
            """Seconds the optional steps may still spend, with the render time already set aside."""
            return budget - (time.time() - t0) - render_reserve
        edit = p.get("edit")  # set when the user edited a finished job in the editor: reuse its transcript + detection
        cuts_pool = cuts_future = None
        if not edit:  # scene cuts run alongside subtitle detection; they steer the transcript's segment boundaries
            cuts_pool = ThreadPoolExecutor(max_workers=1)
            cuts_future = cuts_pool.submit(detect_cuts, video_path)

        # 1. Where are the source subtitles / watermarks? Only those regions get blurred.
        if edit:
            fx = edit.get("fx") or {}
            if fx.get("subtitle_rect"):
                fx_kwargs["subtitle_rect"] = tuple(fx["subtitle_rect"])
            fx_kwargs["watermark_rects"] = [tuple(r) for r in fx.get("watermark_rects", [])]
        elif p["blur_subtitles"] or p["remove_watermark"]:
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

        # 3. Transcribe + translate (an edited job brings its own transcript).
        set_job(job_id, stage="Transcribing and translating", progress=10)
        scene_cut_times: list[float] = []
        if cuts_future:
            try:
                scene_cut_times = cuts_future.result()
                print(f"  {len(scene_cut_times)} scene cuts found", flush=True)
            except Exception as exc:
                print(f"  scene cut detection failed ({exc}); continuing without", flush=True)
            cuts_pool.shutdown(wait=False)
        if edit:
            detected_source_language = edit.get("source_language")
            segments = [{"start": float(e["start"]), "translated_text": e["text"].strip(),
                         "source_text": e.get("source_text", ""), "tempo": e.get("tempo")}
                        for e in edit["segments"] if (e.get("text") or "").strip()]
            if not segments:
                raise RuntimeError("The edited project has no lines.")
        with pipeline_stage("Transcribe + Translate"):
            primary = dub_provider()
            runners = {
                "local": lambda: local_dub.dub(video_path, p["target_language"]),
                "elevenlabs": lambda: elevenlabs_dub(video_path, p["target_language"]),
                "gemini": lambda: gemini_dub.dub(video_path, p["target_language"], retries=2, scene_cuts=scene_cut_times),
            }
            order = [primary] + [n for n in ("elevenlabs", "gemini", "local") if n != primary]  # local last: slow, weakest Burmese
            if os.getenv("DUB_FALLBACK", "").lower() not in ("1", "true"):
                order = [primary]  # fail fast: ElevenLabs costs credits and the local model takes many minutes
            if not os.getenv("ELEVENLABS_API_KEY"):
                order = [n for n in order if n != "elevenlabs"]
            if edit:
                order = []
            for i, name in enumerate(order):
                try:
                    detected_source_language, segments = runners[name]()
                    break
                except Exception as exc:
                    if i == len(order) - 1:
                        raise
                    print(f"  {name} transcribe/translate failed ({exc}); trying {order[i + 1]}", flush=True)
        segments.sort(key=lambda s: s["start"])

        # 3b. Shorten lines that will not fit their scene BEFORE paying for any voice.
        voice_model = dict(edit["voice_model"]) if edit and edit.get("voice_model") else dict(duration_model.DEFAULT)
        if p["fit_translation"] and fit_available() and not edit:
            set_job(job_id, stage="Shortening long lines to fit their scenes", progress=33)
            with pipeline_stage("Pre-fit Translation"):
                prefit_segments(segments, video_duration, job_id, p["target_language"], voice_model, time_left)

        # 4. Voice-over.
        with pipeline_stage(f"Voiceover ({tts_provider()})"):
            if tts_provider() == "gemini":
                gemini_tts._get_client()  # create the shared client before worker threads start
            done = [0]

            def _progress(count: int):
                done[0] += count
                set_job(job_id, stage=f"Voice-over {done[0]}/{len(segments)}",
                        progress=35 + int(25 * done[0] / len(segments)))

            todo, paths = [], {}   # lines that really need the voice: unchanged lines come from the clip cache
            for i, sg in enumerate(segments):
                path = os.path.join(OUTPUT_DIR, f"voice_{job_id}_{i + 1}{audio_ext()}")
                temp_paths.append(path)
                if storage.fetch_clip(clip_name(sg["translated_text"], p["voice_type"]), path):
                    sg["audio_path"], sg["audio_dur"] = path, media_duration(path)
                    _progress(1)
                else:
                    todo.append(i)
                    paths[i] = path
            print(f"  voice-over: {len(todo)} lines to voice ({len(segments) - len(todo)} from cache)", flush=True)
            durs = voice_many([segments[i]["translated_text"] for i in todo], [paths[i] for i in todo],
                              p["voice_type"], voice_model, job_id, _progress)
            for i, d in zip(todo, durs):
                segments[i]["audio_path"], segments[i]["audio_dur"] = paths[i], d

        # 5. Make each line fit its scene.
        if p["fit_translation"] and fit_available() and not edit:
            set_job(job_id, stage="Fitting translation to scene timing", progress=62)
            with pipeline_stage("Fit Translation To Timing"):
                voice_model = duration_model.fit([(sg["translated_text"], sg["audio_dur"]) for sg in segments], voice_model)
                print(f"  voice duration model: {voice_model['a']:.3f}s/syllable + {voice_model['b']:.2f}s", flush=True)
                fit_segments_to_slots(segments, video_duration, job_id, p["voice_type"], p["target_language"],
                                      temp_paths, voice_model, time_left)

        for sg in segments:  # keep rewritten (fitted) clips too
            if "_fit" in sg["audio_path"]:
                storage.put_clip(sg["audio_path"], clip_name(sg["translated_text"], p["voice_type"]))

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
        check_cancelled(job_id)
        set_job(job_id, stage="Rendering video", progress=75)
        with pipeline_stage("FFmpeg Render"):
            result = render(video_path, segments, scenes, effects, output_path, OUTPUT_DIR, job_id)
        srt_path = os.path.join(OUTPUT_DIR, srt_filename)
        write_srt(result["cues"], srt_path)
        video_key = storage.put_output(output_path)  # s3: uploads and removes the local copy
        srt_key = storage.put_output(srt_path)

        voice_model = duration_model.fit([(sg["translated_text"], sg["audio_dur"]) for sg in segments], voice_model)
        by_index = {sc.audio_index: sc for sc in scenes if sc.audio_index is not None}
        project = {
            "voice_model": voice_model,
            "voice": p["voice_type"],
            "source_language": detected_source_language,
            "source_duration": video_duration,
            "max_voice_speedup": p["max_voice_speedup"],
            "cuts": scene_cut_times or (edit or {}).get("cuts", []),
            "fx": {"subtitle_rect": list(fx_kwargs["subtitle_rect"]) if fx_kwargs.get("subtitle_rect") else None,
                   "watermark_rects": [list(r) for r in fx_kwargs.get("watermark_rects", [])]},
            "segments": [
                {"id": i, "start": round(sg["start"], 2), "text": sg["translated_text"],
                 "source_text": sg.get("source_text", ""), "tempo": sg.get("tempo"),
                 "audio_dur": round(sg["audio_dur"], 2),
                 **({"slot": round(sc.src_end - sc.src_start, 2), "out_start": round(sc.out_start, 2),
                     "out_len": round(sc.out_len, 2), "action": sc.action, "applied_tempo": round(sc.tempo, 2)}
                    if (sc := by_index.get(i)) else {})}
                for i, sg in enumerate(segments)
            ],
        }
        print(f"[job {job_id}] finished in {time.time() - t0:.0f}s for a {video_duration:.0f}s video (budget {budget:.0f}s)", flush=True)
        set_job(
            job_id,
            status="done",
            stage="Done",
            progress=100,
            run_seconds=round(time.time() - t0, 1),
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
                "project": project,         # what the editor loads
                "video_file": video_key,   # the API turns these into signed URLs when the client asks
                "subtitle_file": srt_key,
            },
        )
    except JobCancelled:
        print(f"[job {job_id}] cancelled by the user", flush=True)
    except ElevenLabsRateLimited:
        update_job(job_id, status="error", error="ElevenLabs rate-limited this dubbing request. Please retry later.")
    except Exception as exc:
        print(f"[job {job_id}] FAILED: {exc}", flush=True)
        update_job(job_id, status="error", error=f"Recap generation failed: {exc}")
    finally:
        _job_started.pop(job_id, None)
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
    try:
        set_job(job_id, status="running", stage="Starting", progress=1, started_at=time.time())
    except JobCancelled:  # cancelled while waiting in the queue
        return
    video_path = logo_path = None
    try:
        video_path = storage.fetch(input_key)
        logo_path = storage.fetch(logo_key, LOGOS_DIR) if logo_key else None
        run_job(job_id, video_path, logo_path, params)
    except Exception as exc:  # e.g. the upload could not be fetched
        print(f"[job {job_id}] FAILED before start: {exc}", flush=True)
        update_job(job_id, status="error", error=f"Recap generation failed: {exc}")
    finally:
        # Keep the stored source until the retention window ends (storage.cleanup / bucket lifecycle rule):
        # the editor re-renders from it. Only the temporary local copies fetched from s3 are removed.
        if storage.BACKEND == "s3":
            for path in (video_path, logo_path):
                storage.delete_local(path)
