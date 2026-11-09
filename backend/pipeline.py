"""The dubbing pipeline. Runs inside a queue worker (or an in-process thread in dev), never inside a request."""
import hashlib
import shutil
import math
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
import tts_pool
import casting
import looks
import pitch
import gemini_dub
import gemini_tts
import local_dub
import storage
from common import audio_ext, dub_provider, media_duration, tts_provider
from audio_tools import cleanup_separation, make_soft_tone, mix_music, separate_background
from config import LOGOS_DIR, OUTPUT_DIR, UPLOAD_DIR
import usage
from db import Job, Session, update_job
import fit_text
from fit_text import available as fit_available
from scene_cuts import detect_cuts
from recap_engine import (BREATH, EffectOptions, SyncOptions, has_audio, plan_source_timing, plan_timeline, probe_video,
                          render, write_srt)
from subtitle_detect import detect_text_regions, subtitle_windows, to_pixels


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


def clip_voice(voice: str, path: str | None = None, model: str | None = None) -> str:
    """Voice part of a clip's cache name. A clip made by Azure (another voice than the Gemini voice of the same name) gets its own
    key, so Gemini and Azure clips are never mixed in one video through the cache."""
    import azure_tts
    model = model or (tts_pool.model_of(path) if path else None)
    return f"{voice}|azure" if azure_tts.is_azure(model) else voice


def clip_name(text: str, voice: str, style: str | None = None) -> str:
    """Cache name of a voice clip: same text + voice (+ delivery style) = same clip, so an edit only re-voices changed lines."""
    return hashlib.sha1(f"{voice}|{text}{'|' + style if style else ''}".encode()).hexdigest() + audio_ext()


class JobTooSlow(RuntimeError):
    """The job passed its hard time limit: must stop (never swallowed by the 'skip optional step' handlers)."""


class LineBlocked(RuntimeError):
    """Every way of voicing this line (without emotion, other model, milder wording) was refused by the voice service."""


class JobCancelled(Exception):
    """The user pressed Cancel: stop quietly (nothing is saved, nothing is charged)."""


VOICE_SWITCH_WARNING = ("The voice service ran out of requests half way through, so the second part of this video uses a slightly different voice. "
                        "For one voice all the way, try again later, or pick the voice again in the editor and re-render.")


VOICE_AZURE_WARNING = ("The voice service was busy, so all or part of this video was voiced with a standard Burmese voice (Nilar or Thiha) "
                       "instead of the voice you picked. For your own voice, try again later.")


def set_job(job_id: str, **fields):
    usage.flush(job_id)   # keep the saved token totals fresh (throttled)
    if not update_job(job_id, **fields):
        raise JobCancelled(job_id)


JOB_HARD_LIMIT = float(os.getenv("JOB_HARD_LIMIT_SECONDS", "720"))   # a job that runs longer than this fails cleanly
_job_started: dict[str, float] = {}


def check_cancelled(job_id: str):
    """Cheap DB look so long loops stop spending TTS/CPU after Cancel (or once the hard time limit has passed)."""
    started = _job_started.get(job_id)
    if started and time.time() - started > JOB_HARD_LIMIT:
        raise JobTooSlow(f"This video took longer than {JOB_HARD_LIMIT / 60:.0f} minutes (Gemini was slow or busy). "
                           "Please try again; nothing was charged.")
    with Session() as sess:
        job = sess.get(Job, job_id)
        if job is not None and job.status == "cancelled":
            raise JobCancelled(job_id)


def synthesize(text: str, voice: str, path: str, chooser=None, style: str | None = None, ladder: bool = True):
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
        chooser = chooser or tts_pool.Chooser(1)
        look = looks.resolve(voice) if looks.is_look(voice) else None   # character look = base voice + performance notes
        v = look[0] if look else (None if voice == "su" else voice)
        if look:
            style = None   # the look decides the delivery; an emotion direction on top would be read aloud / fight it
        # What to try when the voice service refuses a text (policy): 1) without the emotion direction, 2) on another model
        # (policies differ), 3) with milder wording. A group of lines (ladder=False) just fails so its lines are tried one by one.
        plan = [("cur", text, style, True)]
        if ladder:
            plan += ([("cur", text, None, True)] if style else []) + [("alt", text, None, True), ("cur", None, None, True)]
            if look:
                plan.append(("cur", text, None, False))   # last: the refusal may come from the look's wording -> plain base voice
        last = None
        for kind, variant, st, use_look in plan:
            if variant is None:   # milder wording (one text request)
                try:
                    variant = fit_text.soften(text, "my")
                except Exception:
                    variant = text
                if variant.strip() == text.strip():
                    continue
            while True:
                model = chooser.get() if kind == "cur" else chooser.other(chooser.get())
                if model is None:
                    break
                try:
                    spoken = looks.compose(look[1], variant) if look and use_look else (looks.compose_emotion(st, variant) if st else variant)
                    gemini_tts.synthesize_to_file(spoken, path, v, model=model)
                    return media_duration(path)
                except gemini_tts.QuotaExceeded:
                    if kind == "cur":
                        chooser.failed(model)   # switches to the next model, or raises QuotaExceeded when none is left
                        continue
                    break
                except gemini_tts.ContentBlocked as exc:
                    last = exc
                    print(f"  voice service refused a line ({kind} model{', with emotion' if st else ''}); trying the next way", flush=True)
                    break
        if not ladder:
            raise last or RuntimeError("voice request refused")
        raise LineBlocked(str(last))
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
# Drawn Burmese text is ~1.45x taller than its font size (stacked letters): 0.8 makes our captions ~15% taller than the
# original subtitle's text box ("slightly bigger"). Tune with CAPTION_SIZE_FACTOR after looking at a result.
CAPTION_SIZE_FACTOR = float(os.getenv("CAPTION_SIZE_FACTOR", "0.8"))
# A direction ("Say fearfully:") the TTS READS ALOUD adds ~0.7-1.2 s of English to the clip: a styled clip longer than
# predicted * RATIO + EXTRA is treated as that and re-voiced plainly (was 1.5x + 1.0 s, which let short lines through).
READ_ALOUD_RATIO = float(os.getenv("READ_ALOUD_RATIO", "1.25"))
READ_ALOUD_EXTRA = float(os.getenv("READ_ALOUD_EXTRA", "0.45"))
EMOTION_MAX = int(os.getenv("EMOTION_MAX_LINES", "12"))   # emotional lines are voiced one per request: cap them (quota + time)
# Time budget: a video must be finished in about its own length (hard cap JOB_BUDGET_MAX seconds). The optional
# polishing steps (pre-fit, fit rounds) only start if enough budget is left AFTER reserving time for the render.
JOB_BUDGET_MAX = float(os.getenv("JOB_BUDGET_MAX_SECONDS", "540"))
RENDER_SECONDS_PER_VIDEO_SECOND = float(os.getenv("RENDER_SECONDS_PER_VIDEO_SECOND", "0.2"))   # measured 0.14 on an M2 Air


def plan_batches(texts: list[str], voices: list[str], styles: list) -> list[list[int]]:
    """Which lines go into which TTS request: lines of the same voice share requests (several sentences each);
    lines with an emotion direction are voiced one per request (the direction applies to a single line)."""
    plain = [i for i in range(len(texts)) if not styles[i]]
    batches: list[list[int]] = []
    for v in dict.fromkeys(voices[i] for i in plain):
        idxs = [i for i in plain if voices[i] == v]
        sub = bulk_tts.make_batches([texts[i] for i in idxs]) if TTS_BULK else [[k] for k in range(len(idxs))]
        batches += [[idxs[k] for k in b] for b in sub]
    return batches + [[i] for i in range(len(texts)) if styles[i]]


def voice_many(texts: list[str], paths: list[str], voice, model: dict, job_id: str, progress=None,
               chooser=None, styles: list | None = None, blocked: list | None = None) -> list[float]:
    """Voice many lines with as few requests as possible (several lines per request when TTS_BULK is on; a group
    whose audio can't be split reliably is retried as two smaller groups, then line by line). `voice` is one voice or
    a list (one per line); `styles` = emotion directions per line (None = plain) - a style the TTS reads aloud
    instead of acting is detected by the clip length and dropped (written back into `styles`). Returns the durations."""
    n = len(texts)
    voices = list(voice) if isinstance(voice, (list, tuple)) else [voice] * n
    if styles is None:
        styles = [None] * n
    for i in range(n):
        if looks.is_look(voices[i]):
            styles[i] = None
    durs = [0.0] * n

    def single(i: int):
        check_cancelled(job_id)
        try:
            durs[i] = synthesize(texts[i], voices[i], paths[i], chooser, styles[i])
        except (JobCancelled, gemini_tts.QuotaExceeded):
            raise
        except Exception as exc:   # refused every way, or failed after retries: a silent clip of the expected length, subtitle still shows
            print(f"  line refused by the voice service, left silent: {texts[i][:40]}... ({exc})", flush=True)
            durs[i] = max(duration_model.predict(texts[i], model), 0.8)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono:d={durs[i]:.2f}",
                            paths[i]], check=True)
            if blocked is not None:
                blocked.append(i)
            if progress:
                progress(1)
            return
        if styles[i] and durs[i] > duration_model.predict(texts[i], model) * READ_ALOUD_RATIO + READ_ALOUD_EXTRA:
            print(f"  emotion '{styles[i]}' was probably read aloud ({durs[i]:.1f}s); voicing the line plainly", flush=True)
            styles[i] = None
            durs[i] = synthesize(texts[i], voices[i], paths[i], chooser, None)
        elif styles[i] and tts_provider() == "gemini":   # an emotion direction can pull the voice to another pitch (male -> female)
            try:
                bad, got, ref = pitch.drifted(paths[i], voices[i])
            except Exception:
                bad = False
            if bad:
                print(f"  emotion '{styles[i]}' moved the voice {voices[i]} from {ref:.0f} Hz to {got:.0f} Hz; voicing the line plainly", flush=True)
                styles[i] = None
                durs[i] = synthesize(texts[i], voices[i], paths[i], chooser, None)
        storage.put_clip(paths[i], clip_name(texts[i], clip_voice(voices[i], paths[i]), styles[i]))
        if progress:
            progress(1)

    def group(idx: list[int]):
        check_cancelled(job_id)
        if len(idx) > 1:
            v = voices[idx[0]]
            try:
                ok = bulk_tts.synthesize_batch([texts[i] for i in idx], v, [paths[i] for i in idx],
                                               lambda text, path: synthesize(text, v, path, chooser, ladder=False), OUTPUT_DIR, model)
                if ok:
                    for i in idx:
                        durs[i] = media_duration(paths[i])
                        storage.put_clip(paths[i], clip_name(texts[i], clip_voice(voices[i], paths[i])))
                    if progress:
                        progress(len(idx))
                    return
                print(f"  bulk voice split not trusted for {len(idx)} lines; trying two smaller groups", flush=True)
                half = len(idx) // 2
                group(idx[:half])
                group(idx[half:])
                return
            except (JobCancelled, gemini_tts.QuotaExceeded):
                raise   # cancelled, or the daily limit is used up: more requests would only be refused
            except Exception as exc:
                print(f"  bulk voice failed ({exc}); using one request each", flush=True)
        for i in idx:
            single(i)

    with ThreadPoolExecutor(max_workers=TTS_WORKERS) as pool:
        list(pool.map(group, plan_batches(texts, voices, styles)))
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


def fit_segments_to_slots(segments, video_duration, job_id, voice, target_language, temp_paths, model, time_left=None,
                          chooser=None):
    """AFTER voicing, with real lengths: make each voice line last about as long as the original speech of its scene,
    by rewriting the SCRIPT: too long -> shortened, too short -> lengthened with faithful detail (no dead air).
    Voice speed is only the last resort and is handled by the timeline. Dead air the SOURCE really has is kept.

    Built for speed: lines go to the LLM in bulk, each rewrite is checked with the duration model before any voice is
    paid for, and accepted rewrites are voiced together in batched TTS requests."""
    for round_no in range(FIT_ROUNDS):
        todo = {}
        for i in range(len(segments)):
            if segments[i].get("silent"):
                continue
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
        fit_styles = [segments[i].get("style") for i in voiced]
        durs = voice_many([current[i] for i in voiced], paths, [segments[i]["voice"] for i in voiced], model, job_id,
                          prog, chooser, fit_styles)
        changed = 0
        for i, path, new_dur, new_style in zip(voiced, paths, durs, fit_styles):
            mode, _tgt = todo[i]
            upper, want = _slot_bounds(segments, i, video_duration)
            dur = segments[i]["audio_dur"]
            better = (new_dur < dur) if mode == "shorten" else (
                new_dur > dur and new_dur <= upper * 1.05 and abs(new_dur - want) < abs(dur - want))
            if better:
                segments[i].update(translated_text=current[i], audio_path=path, audio_dur=new_dur, style=new_style)
                changed += 1
        print(f"  fit round {round_no + 1}: {changed} of {len(voiced)} rewrites kept", flush=True)


_ASPECTS = {"9:16": (9, 16), "1:1": (1, 1), "4:5": (4, 5), "16:9": (16, 9)}


def _out_size(aspect: str, info: dict):
    """Final frame (w, h) for the chosen format, short side = min(1080, source short side) (no upscaling); None = keep the source."""
    if aspect not in _ASPECTS:
        return None
    a, b = _ASPECTS[aspect]
    short = max(360, min(1080, min(info["width"], info["height"]))) // 2 * 2
    if a <= b:
        w, h = short, round(short * b / a)
    else:
        w, h = round(short * a / b), short
    size = (w // 2 * 2, h // 2 * 2)
    return None if size == (info["width"], info["height"]) else size


def _manual_blur_pixels(rects, size: tuple) -> list:
    """User-drawn blur boxes (fractions of the OUTPUT frame) -> even pixel rects (x, y, w, h)."""
    W, H = size
    out = []
    for x, y, w, h in rects or []:
        px, py = int(x * W) // 2 * 2, int(y * H) // 2 * 2
        pw, ph = max(int(w * W) // 2 * 2, 8), max(int(h * H) // 2 * 2, 8)
        out.append((px, py, min(pw, W - px), min(ph, H - py)))
    return out


def run_job(job_id: str, video_path: str, logo_path: str | None, p: dict):
    output_filename = f"recap_output_{job_id}.mp4"
    srt_filename = f"recap_output_{job_id}.srt"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    t0 = time.time()
    _job_started[job_id] = t0
    temp_paths: list[str] = []
    mode = p.get("mode", "recap")               # "recap" (one narrator voice) | "full" (characters, emotions, original sound)
    dub = p.get("output", "dub") != "subtitles"  # False: keep the original audio, only add Burmese subtitles
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
            if fx.get("subtitle_windows") is not None:
                fx_kwargs["subtitle_windows"] = [tuple(w) for w in fx["subtitle_windows"]]
            fx_kwargs["watermark_rects"] = [tuple(r) for r in fx.get("watermark_rects", [])]
            if fx.get("caption_px"):
                fx_kwargs["caption_px"] = int(fx["caption_px"])
        elif p["blur_subtitles"] or p["remove_watermark"]:
            set_job(job_id, stage="Detecting subtitles", progress=3)
            with pipeline_stage("Subtitle Detection"):
                try:
                    found = detect_text_regions(video_path, video_duration)
                    if found["subtitle"]:
                        fx_kwargs["subtitle_rect"] = to_pixels(found["subtitle"], info["width"], info["height"])
                        if found.get("line_height"):   # our captions: only slightly bigger than the original ones
                            fx_kwargs["caption_px"] = int(found["line_height"] * info["height"] * CAPTION_SIZE_FACTOR)
                    fx_kwargs["watermark_rects"] = [
                        to_pixels(r, info["width"], info["height"], 0.01, 0.005) for r in found["watermarks"]
                    ]
                    if found["subtitle"] and p["blur_subtitles"]:   # blur only while a subtitle is really there
                        wins = subtitle_windows(video_path, video_duration, found["subtitle"])
                        if wins is not None:
                            fx_kwargs["subtitle_windows"] = wins
                            print(f"  subtitle on screen in {len(wins)} windows ({sum(b - a for a, b in wins):.0f}s of {video_duration:.0f}s)", flush=True)
                    print(f"  subtitles: {found['subtitle']}  watermarks: {len(found['watermarks'])}", flush=True)
                except Exception as exc:  # OCR unavailable: fall back to the classic lower-third strip
                    print(f"  detection failed ({exc}); using fixed lower-third", flush=True)
                    fx_kwargs["subtitle_rect"] = (0, int(info["height"] * 0.72) // 2 * 2,
                                                  info["width"] // 2 * 2, int(info["height"] * 0.25) // 2 * 2)
        set_job(job_id, subtitles_detected=bool(fx_kwargs.get("subtitle_rect")))

        # 2. Keep the original music/effects (voice removed) — runs alongside dubbing.
        src_has_audio = has_audio(video_path)
        bg_choice = p.get("background") or ("separate" if p.get("keep_background") else ("separate" if mode == "full" else "off"))
        if not dub or not src_has_audio:
            bg_choice = "off"
        warn: list[str] = []
        # The separated music/effects of a video are cached (an editor re-render of the same video must not run Demucs again).
        bg_cache = os.path.join(OUTPUT_DIR, f"bgcache_{p.get('bg_source_job') or job_id}.wav")
        if bg_choice == "separate" and os.path.isfile(bg_cache):
            bg_state["path"] = bg_cache
        elif bg_choice == "separate":
            def _separate():
                try:
                    found_path = separate_background(video_path, OUTPUT_DIR, job_id)
                    shutil.copyfile(found_path, bg_cache)
                    bg_state["path"] = bg_cache
                except Exception as exc:
                    bg_state["error"] = str(exc)
            bg_thread = threading.Thread(target=_separate, daemon=True)
            bg_thread.start()

        # 3. Transcribe + translate (an edited job brings its own transcript).
        set_job(job_id, stage="Transcribing and translating", progress=10)
        scene_cut_times: list[float] = []
        skipped_parts: list[tuple[float, float]] = []   # audio Gemini refused to transcribe even in small pieces
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
                         "source_text": e.get("source_text", ""), "tempo": e.get("tempo"),
                         "speaker": e.get("speaker"), "emotion": e.get("emotion"), "style": e.get("style"),
                         "gender": ((edit.get("speakers") or {}).get(e.get("speaker")) or {}).get("gender")}
                        for e in edit["segments"] if (e.get("text") or "").strip()]
            for k, sg in enumerate(segments):   # a line added in the editor speaks with the previous line's character
                if not sg["speaker"] and mode == "full":
                    sg["speaker"] = segments[k - 1]["speaker"] if k else None
            if not segments:
                raise RuntimeError("The edited project has no lines.")
        with pipeline_stage("Transcribe + Translate"):
            primary = dub_provider()
            runners = {
                "local": lambda: local_dub.dub(video_path, p["target_language"]),
                "elevenlabs": lambda: elevenlabs_dub(video_path, p["target_language"]),
                "gemini": lambda: gemini_dub.dub(video_path, p["target_language"], retries=3, scene_cuts=scene_cut_times,
                                                 skipped=skipped_parts),
            }
            if mode == "full":
                runners["gemini"] = lambda: gemini_dub.dub(video_path, p["target_language"], retries=3,
                                                           scene_cuts=scene_cut_times, mode="full", skipped=skipped_parts)
                primary = "gemini"   # only the Gemini path knows speakers, emotions and the natural-Burmese rules
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
        if p["fit_translation"] and fit_available() and not edit and dub:
            set_job(job_id, stage="Shortening long lines to fit their scenes", progress=31)
            with pipeline_stage("Pre-fit Translation"):
                try:
                    prefit_segments(segments, video_duration, job_id, p["target_language"], voice_model, time_left)
                except (JobCancelled, JobTooSlow, gemini_tts.QuotaExceeded):
                    raise
                except Exception as exc:   # optional polishing: the film is still made without it
                    print(f"  pre-fit failed ({exc}); continuing without it", flush=True)

        # 3c. Casting: every line gets its voice. Full movie: one fixed voice per character (the most talkative one gets
        # the voice the user picked); lines with a clear emotion get a delivery direction (capped: one request each).
        speakers = None
        chooser = None
        if mode == "full" and dub:
            known = {sid: v["voice"] for sid, v in ((edit or {}).get("speakers") or {}).items()}
            suggested = {} if (edit or tts_provider() != "gemini" or os.getenv("LLM_CASTING", "1") == "0") \
                else casting.llm_choice(segments)   # one text request; editor re-renders keep the voices they have
            speakers = casting.assign_voices(segments, p["voice_type"], known, suggested)
            print("  casting: " + ", ".join(f"{sid}={v['voice']} ({v['lines']} lines)" for sid, v in speakers.items()), flush=True)
            if p.get("emotion", True) and tts_provider() in ("gemini", "fake") and not edit:
                cand = [i for i, sg in enumerate(segments) if gemini_dub.EMOTIONS.get(sg.get("emotion") or "neutral")
                        and not looks.is_look(sg.get("voice"))]
                if len(cand) > EMOTION_MAX:
                    cand = [cand[int(k * len(cand) / EMOTION_MAX)] for k in range(EMOTION_MAX)]
                for i in cand:
                    segments[i]["style"] = gemini_dub.EMOTIONS[segments[i]["emotion"]]
                print(f"  emotions: {len(cand)} lines get a delivery direction", flush=True)
        else:
            for sg in segments:
                sg["voice"] = p["voice_type"]

        if dub:
            # 4. Voice-over.
            with pipeline_stage(f"Voiceover ({tts_provider()})"):
                if tts_provider() == "gemini":
                    gemini_tts._get_client()  # create the shared client before worker threads start
                done = [0]

                def _progress(count: int):
                    done[0] += count
                    set_job(job_id, stage=f"Voice-over {done[0]}/{len(segments)}",
                            progress=35 + int(25 * done[0] / len(segments)))

                set_job(job_id, stage=f"Voice-over 0/{len(segments)}", progress=35)  # show the new step right away
                todo, paths = [], {}   # lines that really need the voice: unchanged lines come from the clip cache
                for i, sg in enumerate(segments):
                    path = os.path.join(OUTPUT_DIR, f"voice_{job_id}_{i + 1}{audio_ext()}")
                    temp_paths.append(path)
                    if storage.fetch_clip(clip_name(sg["translated_text"], clip_voice(sg["voice"], model=(edit or {}).get("tts_model")), sg.get("style")), path):
                        sg["audio_path"], sg["audio_dur"] = path, media_duration(path)
                        _progress(1)
                    else:
                        todo.append(i)
                        paths[i] = path
                print(f"  voice-over: {len(todo)} lines to voice ({len(segments) - len(todo)} from cache)", flush=True)
                t_texts = [segments[i]["translated_text"] for i in todo]
                t_voices = [segments[i]["voice"] for i in todo]
                t_styles = [segments[i].get("style") for i in todo]
                groups = len(plan_batches(t_texts, t_voices, t_styles))
                chooser = (tts_pool.Chooser(groups + max(4, groups // 3), (edit or {}).get("tts_model") or p.get("reserved_model") or None, job_id, p.get("mode"))
                           if tts_provider() == "gemini" and todo else None)   # + room for the fit rewrites
                blocked_idx: list[int] = []
                durs = voice_many(t_texts, [paths[i] for i in todo], t_voices, voice_model, job_id, _progress, chooser, t_styles,
                                  blocked_idx)
                for i, d, st in zip(todo, durs, t_styles):
                    segments[i]["audio_path"], segments[i]["audio_dur"], segments[i]["style"] = paths[i], d, st
                for k in blocked_idx:   # silent lines: not cached, not fitted, reported
                    segments[todo[k]]["silent"] = True
                    segments[todo[k]]["style"] = None
                if len(blocked_idx) > max(5, 0.25 * len(todo)):
                    raise RuntimeError(f"The voice service failed or refused {len(blocked_idx)} of {len(todo)} lines, so the "
                                       "film would be mostly silent. Please try again later.")
                if blocked_idx:
                    when = ", ".join(f"{segments[todo[k]]['start']:.0f}s" for k in blocked_idx[:8])
                    warn.append(f"The voice service refused {len(blocked_idx)} line(s) for policy reasons, so they stay silent "
                                f"(subtitles still show), at: {when}. Reword them in the editor and re-render.")

            # 5. Make each line fit its scene.
            if p["fit_translation"] and fit_available() and not edit and dub:
                set_job(job_id, stage="Fitting translation to scene timing", progress=62)
                with pipeline_stage("Fit Translation To Timing"):
                    voice_model = duration_model.fit([(sg["translated_text"], sg["audio_dur"]) for sg in segments], voice_model)
                    print(f"  voice duration model: {voice_model['a']:.3f}s/syllable + {voice_model['b']:.2f}s", flush=True)
                    try:
                        fit_segments_to_slots(segments, video_duration, job_id, p["voice_type"], p["target_language"],
                                              temp_paths, voice_model, time_left, chooser)
                    except (JobCancelled, JobTooSlow, gemini_tts.QuotaExceeded):
                        raise
                    except Exception as exc:   # optional polishing: keep the lines as they are
                        print(f"  fitting failed ({exc}); continuing without further fitting", flush=True)

            for sg in segments:  # keep rewritten (fitted) clips too
                if "_fit" in sg["audio_path"]:
                    storage.put_clip(sg["audio_path"], clip_name(sg["translated_text"], clip_voice(sg["voice"], sg["audio_path"]), sg.get("style")))

        else:   # subtitles only: no voice, the video keeps its own sound and timing
            for k, sg in enumerate(segments):
                nxt = segments[k + 1]["start"] if k + 1 < len(segments) else video_duration
                sg["audio_path"] = ""
                sg["audio_dur"] = round(max(min((sg.get("end") or nxt) - sg["start"], nxt - sg["start"]), 0.2), 2)

        # 6. Sync timeline + render.
        set_job(job_id, stage="Building sync timeline", progress=68)
        scenes = plan_source_timing(segments, video_duration) if not dub else plan_timeline(
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

        bg_path, duck = bg_state.get("path"), False
        if bg_choice == "original":   # keep the film's own music and sounds, lowered while the characters speak
            bg_path, duck = video_path, True
        if bg_thread:
            set_job(job_id, stage="Separating background music", progress=70)
            bg_thread.join(timeout=max(budget - (time.time() - t0) - 0.5 * render_reserve, 30.0))
            if "path" not in bg_state:
                why = bg_state.get("error") or "it was still running when the time budget ran out"
                print(f"  background separation failed: {why}", flush=True)
                if mode == "full":   # the film's own sound, lowered under the voice, is better than silence
                    bg_choice, bg_path, duck = "original", video_path, True
                    warn.append("The original speech could not be removed from the film's sound in time, so the original "
                                "audio is kept quietly under the Burmese voice instead.")

        out_size = _out_size(p.get("aspect", "original"), info)
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
            logo_xy=((p["logo_x"], p["logo_y"]) if p.get("logo_x", -1) >= 0 and p.get("logo_y", -1) >= 0 else None),
            extra_blur_rects=_manual_blur_pixels(p.get("manual_blurs"), out_size or (info["width"], info["height"])),
            out_size=out_size, fit_mode=p.get("fit_mode", "blur"),
            pan_x=float(p.get("pan_x", 0.5)), pan_y=float(p.get("pan_y", 0.5)),
            captions=p["enable_subtitles"],
            background_path=bg_state.get("path") if not duck else bg_path,
            duck_background=duck,
            background_volume=float(p["bg_volume"]) if p.get("bg_volume") is not None else (0.7 if duck else 0.8),
            source_audio=(not dub and src_has_audio),
            **fx_kwargs,
        )
        check_cancelled(job_id)
        set_job(job_id, stage="Rendering video", progress=75)
        with pipeline_stage("FFmpeg Render"):
            result = render(video_path, segments, scenes, effects, output_path, OUTPUT_DIR, job_id)
            if p.get("soft_music"):   # optional quiet pad under everything
                try:
                    tone = os.path.join(OUTPUT_DIR, f"{job_id}_tone.wav")
                    temp_paths.append(tone)
                    make_soft_tone(tone, result["duration"])
                    mix_music(output_path, tone)
                except Exception as exc:
                    print(f"  soft music failed ({exc}); continuing without", flush=True)
        srt_path = os.path.join(OUTPUT_DIR, srt_filename)
        write_srt(result["cues"], srt_path)
        video_key = storage.put_output(output_path)  # s3: uploads and removes the local copy
        srt_key = storage.put_output(srt_path)

        voice_model = duration_model.fit([(sg["translated_text"], sg["audio_dur"]) for sg in segments], voice_model)
        by_index = {sc.audio_index: sc for sc in scenes if sc.audio_index is not None}
        import azure_tts
        if chooser is not None and any(azure_tts.is_azure(m) for m in chooser.models_used):
            warn.append(VOICE_AZURE_WARNING)    # a standard Burmese voice (Nilar / Thiha) was used instead of the picked one
        elif chooser is not None and chooser.switches and VOICE_SWITCH_WARNING not in warn:
            warn.append(VOICE_SWITCH_WARNING)   # shown with the result (English + Burmese): the voice changed mid-video
        project = {
            "voice_model": voice_model,
            "voice": p["voice_type"],
            "tts_model": chooser.get() if chooser else (edit or {}).get("tts_model"),
            "source_language": detected_source_language,
            "source_duration": video_duration,
            "max_voice_speedup": p["max_voice_speedup"],
            "cuts": scene_cut_times or (edit or {}).get("cuts", []),
            "mode": mode,
            "output": "dub" if dub else "subtitles",
            "speakers": speakers,
            "fx": {"subtitle_rect": list(fx_kwargs["subtitle_rect"]) if fx_kwargs.get("subtitle_rect") else None,
                   "caption_px": fx_kwargs.get("caption_px"),
                   "watermark_rects": [list(r) for r in fx_kwargs.get("watermark_rects", [])],
                   "subtitle_windows": [list(w) for w in fx_kwargs["subtitle_windows"]] if fx_kwargs.get("subtitle_windows") is not None else None},
            "segments": [
                {"id": i, "start": round(sg["start"], 2), "text": sg["translated_text"],
                 "source_text": sg.get("source_text", ""), "tempo": sg.get("tempo"),
                 "speaker": sg.get("speaker") if mode == "full" else None, "emotion": sg.get("emotion"),
                 "style": sg.get("style"),
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
                "background_kept": "path" in bg_state or bg_choice == "original",
                "warnings": warn + ([f"Gemini refused to transcribe {len(skipped_parts)} short part(s) of this video "
                              f"({', '.join(f'{a:.0f}-{b:.0f}s' for a, b in skipped_parts[:6])}); those parts have no "
                              "translation. Add lines there in the editor."] if skipped_parts else []),
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
    except gemini_tts.QuotaExceeded as exc:
        print(f"[job {job_id}] stopped: {exc}", flush=True)
        update_job(job_id, status="error", error=str(exc))
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
    usage.install()
    usage.start(job_id)   # every Gemini / Claude answer from here on is counted for this video
    try:
        video_path = storage.fetch(input_key)
        logo_path = storage.fetch(logo_key, LOGOS_DIR) if logo_key else None
        run_job(job_id, video_path, logo_path, params)
    except Exception as exc:  # e.g. the upload could not be fetched
        print(f"[job {job_id}] FAILED before start: {exc}", flush=True)
        update_job(job_id, status="error", error=f"Recap generation failed: {exc}")
    finally:
        usage.flush(job_id, force=True)   # also for failed / cancelled videos: their tokens were paid
        usage.forget(job_id)
        # Keep the stored source until the retention window ends (storage.cleanup / bucket lifecycle rule):
        # the editor re-renders from it. Only the temporary local copies fetched from s3 are removed.
        if storage.BACKEND == "s3":
            for path in (video_path, logo_path):
                storage.delete_local(path)


def preview_line(text: str, voice: str, style: str | None, model: dict, preferred_model: str | None = None, mode: str | None = None) -> str:
    """Voice ONE line right now (editor preview). The clip goes into the same cache the render uses
    (key = voice + text + style), so pressing Apply afterwards does not pay for it again. Returns the clip's local path."""
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "preview" + audio_ext())
    if storage.fetch_clip(clip_name(text, clip_voice(voice, model=preferred_model), style), path):
        return path
    chooser = tts_pool.Chooser(1, preferred_model, mode=mode) if tts_provider() == "gemini" else None
    styles = [style]
    voice_many([text], [path], [voice], model, "", None, chooser, styles)
    if styles[0] != style:   # the direction was read aloud / bent the pitch and was dropped: also cache the plain clip under the old key
        storage.put_clip(path, clip_name(text, clip_voice(voice, path), style))
    return path
