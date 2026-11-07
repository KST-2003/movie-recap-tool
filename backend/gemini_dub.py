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
CHUNK_SECONDS = float(os.getenv("GEMINI_DUB_CHUNK_SECONDS", "75"))
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


CPS = float(os.getenv("BURMESE_CPS", "10"))  # Burmese characters a TTS voice reads per second (calibrate with real clips)
MAX_CUT_HINTS = 120
# Tone for the Burmese narration. Override with DUB_STYLE_NOTE in .env to tune it without touching code.
DEFAULT_STYLE = (
    "Write like a popular Myanmar movie-recap storyteller: spoken, colloquial Burmese (sentence endings like "
    "တယ် / ပါတယ်, not literary သည် / ၏), warm, vivid and gripping, as if telling the story to a friend. "
    "Use natural connecting words (then, but, suddenly, because of that) so the lines flow into each other."
)
STYLE_NOTE = os.getenv("DUB_STYLE_NOTE", DEFAULT_STYLE)


def _prompt(target: str, cuts: list[float] | None = None) -> str:
    text = (
        "This audio is the narration of a fast-cut recap video (the picture changes every 1-3 seconds). "
        "Transcribe all spoken dialogue into segments with precise start/end times in seconds from the start of "
        "this audio, then translate each segment into " + target + " for a voice-over. Skip music and silence. "
        "Segments must not overlap and must be in chronological order. Also report the source language as an ISO code.\n"
        "MEANING FIRST: translate what is actually said. Keep every key fact, action, name, number and cause/effect; "
        "never invent, skip or change the meaning, and do not soften or exaggerate it. Names must stay consistent "
        "across all segments. Each translated_text must be a complete, grammatical sentence (or clause) that makes "
        "sense on its own and also reads naturally after the previous line. Never cut a sentence in the middle.\n"
        f"TONE: {STYLE_NOTE}\n"
        "LENGTH: every line is read aloud inside its own time slot (end - start) and should FILL it: not much "
        "shorter (no dead air where the source speaker was talking) and not longer. If the source speech is dense "
        "and continuous, the translation must be just as dense; leave silence only where the source really has "
        f"a pause. Aim for about {CPS:g} characters per second of slot and stay under {CPS * 1.3:g}. To save length, choose shorter "
        "wording and drop filler or repeated words, but do NOT drop information and do NOT turn the sentence into "
        "clipped, robotic fragments. If a source sentence is too long for its slot, split it into two segments at a "
        "natural pause instead of cutting its meaning.\n"
        "BOUNDARIES: end a segment at a natural pause or sentence end, preferring a moment that coincides with a "
        "scene cut. Never merge several sentences into one long segment.\n"
        "PUNCTUATION: use proper punctuation: a period (။) at the end of each sentence and commas at natural breath "
        "points, because the TTS voice pauses on them."
    )
    if cuts:
        shown = ", ".join(f"{c:.1f}" for c in cuts[:MAX_CUT_HINTS])
        text += f"\nSCENE CUTS in the picture, at these seconds from the start of this audio: {shown}."
    return text


def _dub_chunk(audio_path: str, offset: float, target: str, attempts: int,
               cuts: list[float] | None = None) -> tuple[str | None, list[dict]]:
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
                    contents=[uploaded, _prompt(target, cuts)],
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
        retries: int | None = None, scene_cuts: list[float] | None = None) -> tuple[str | None, list[dict]]:
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
                paths.append((audio, 0.0, b))
                continue
            p = os.path.join(tmp, f"chunk{n}.mp3")
            _run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", audio, "-c", "copy", p])
            paths.append((p, a, b))
        print(f"  transcribing {len(paths)} chunk(s) in parallel", flush=True)
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(paths))) as pool:
            results = list(pool.map(
                lambda pab: _dub_chunk(pab[0], pab[1], target, attempts,
                                       [c - pab[1] for c in scene_cuts or [] if pab[1] <= c < pab[2]]),
                paths))

    source = next((lang for lang, _ in results if lang), None)
    segments = sorted((s for _, segs in results for s in segs), key=lambda s: s["start"])
    if not segments:
        raise RuntimeError("Gemini returned no translated timed transcript segments.")
    return source, finish_segments(segments, scene_cuts or [])


def finish_segments(segments: list[dict], cuts: list[float]) -> list[dict]:
    """Snap segment starts/ends onto scene cuts (so a voice line begins with its scene), then measure
    characters-per-second and flag lines that are probably too long for their slot."""
    from scene_cuts import snap

    prev_end = 0.0
    for sg in segments:
        start, end = snap(sg["start"], cuts), snap(sg["end"], cuts)
        if start >= prev_end - 0.05 and end > start + 0.2:
            sg["start"], sg["end"] = max(start, prev_end), end
        prev_end = sg["end"]
    flagged = 0
    for sg in segments:
        sg["cps"] = round(len(sg["translated_text"]) / max(sg["end"] - sg["start"], 0.2), 1)
        sg["too_long"] = sg["cps"] > CPS * 1.35  # more than the voice can be sped up to
        flagged += sg["too_long"]
    print(f"  {len(segments)} segments, {flagged} flagged too long for their slot (> {CPS * 1.35:.0f} chars/s)", flush=True)
    return segments
