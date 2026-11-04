"""Gemini-based transcribe + translate. Long audio is cut at silences and processed in parallel."""
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from gemini_tts import _get_client

MODEL = os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash")
CHUNK_SECONDS = float(os.getenv("GEMINI_DUB_CHUNK_SECONDS", "150"))
THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))  # 0 = no hidden reasoning: several times faster
WORKERS = int(os.getenv("GEMINI_DUB_WORKERS", "6"))
LANGUAGE_NAMES = {"my": "Burmese (Myanmar)", "en": "English", "th": "Thai", "zh": "Chinese"}

SCHEMA = {
    "type": "object",
    "properties": {
        "source_language": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "source_text": {"type": "string"},
                    "translated_text": {"type": "string"},
                },
                "required": ["start", "end", "source_text", "translated_text"],
            },
        },
    },
    "required": ["segments"],
}


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=timeout)


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return float(out.stdout.strip())


def _silence_midpoints(path: str) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "silencedetect=noise=-30dB:d=0.2", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return [(a + b) / 2 for a, b in zip(starts, ends)]


def _plan_chunks(path: str, total: float) -> list[tuple[float, float]]:
    """Cut points at silences near every CHUNK_SECONDS so no sentence is split in half."""
    if total <= CHUNK_SECONDS * 1.3:
        return [(0.0, total)]
    silences = _silence_midpoints(path)
    cuts, cur = [], 0.0
    while total - cur > CHUNK_SECONDS * 1.3:
        target = cur + CHUNK_SECONDS
        window = [s for s in silences if cur + CHUNK_SECONDS * 0.6 <= s <= cur + CHUNK_SECONDS * 1.4]
        cur = min(window, key=lambda s: abs(s - target)) if window else target
        cuts.append(cur)
    bounds = [0.0] + cuts + [total]
    return list(zip(bounds[:-1], bounds[1:]))


def _prompt(target: str) -> str:
    return (
        "Transcribe all spoken dialogue in this audio into sentence-level segments with precise start/end "
        f"times in seconds from the beginning. Translate each segment into natural, spoken {target} suitable "
        "for a voice-over (no notes, no romanization). Skip music and silence. Segments must not overlap "
        "and must be in chronological order. Also report the source language as an ISO code.\n"
        "TIMING IS CRITICAL: the translation will be read aloud by a TTS voice and must fit inside the "
        "segment's own duration (end - start). Burmese TTS reads roughly 10-12 characters per second, so keep "
        "translated_text at or below about 10 x (end - start) characters. Be concise: keep the key meaning, "
        "drop filler words, repetition and honorifics, and prefer short common words. A translation that is "
        "shorter than the original speech is better than one that is longer."
    )


def _dub_chunk(audio_path: str, offset: float, target: str, attempts: int) -> tuple[str | None, list[dict]]:
    from google.genai import types

    client = _get_client()
    uploaded = client.files.upload(file=audio_path, config={"mime_type": "audio/mpeg"})
    try:
        deadline = time.monotonic() + 600
        while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
            if time.monotonic() > deadline:
                raise TimeoutError("Gemini file processing timed out.")
            time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)
        for attempt in range(attempts):
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=[uploaded, _prompt(target)],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", response_schema=SCHEMA, temperature=0.2,
                        thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET)),
                )
                break
            except Exception as exc:
                err = str(exc).lower()
                transient = any(k in err for k in ("429", "500", "503", "resource_exhausted", "unavailable", "timeout", "too_many_requests"))
                if "per day" in err or "perday" in err:
                    transient = False
                if not transient or attempt == attempts - 1:
                    raise
                wait = min(5 * 2 ** attempt, 60)
                print(f"  Gemini busy ({exc.__class__.__name__}); retry {attempt + 1}/{attempts - 1} in {wait}s", flush=True)
                time.sleep(wait)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
    data = json.loads(response.text)
    segments = []
    for s in data.get("segments", []):
        text = (s.get("translated_text") or "").strip()
        start, end = float(s["start"]) + offset, float(s["end"]) + offset
        if text and end > start:
            segments.append({"start": start, "end": end,
                             "source_text": s.get("source_text", ""), "translated_text": text})
    return data.get("source_language"), segments


def dub(video_path: str, target_language: str, timeout_seconds: int = 600,
        retries: int | None = None) -> tuple[str | None, list[dict]]:
    """Transcribe the speech, translate it, and return (source_language, segments) with timings in seconds."""
    target = LANGUAGE_NAMES.get(target_language, target_language)
    attempts = retries or int(os.getenv("GEMINI_DUB_RETRIES", "6"))
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.mp3")
        _run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", audio])
        chunks = _plan_chunks(audio, _duration(audio))
        paths = []
        for n, (a, b) in enumerate(chunks):
            if len(chunks) == 1:
                paths.append((audio, 0.0))
                continue
            p = os.path.join(tmp, f"chunk{n}.mp3")
            _run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", audio, "-c", "copy", p])
            paths.append((p, a))
        print(f"  transcribing {len(paths)} chunk(s) in parallel", flush=True)
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(paths))) as pool:
            results = list(pool.map(lambda pa: _dub_chunk(pa[0], pa[1], target, attempts), paths))

    source = next((lang for lang, _ in results if lang), None)
    segments = sorted((s for _, segs in results for s in segs), key=lambda s: s["start"])
    if not segments:
        raise RuntimeError("Gemini returned no translated timed transcript segments.")
    return source, segments
