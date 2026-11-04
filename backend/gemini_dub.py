"""Gemini-based transcribe + translate (replaces ElevenLabs Dubbing). Returns timed, translated segments."""
import json
import os
import subprocess
import tempfile
import time

from gemini_tts import _get_client

MODEL = os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash")
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


def _extract_audio(video_path: str, out_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=300,
    )


def dub(video_path: str, target_language: str, timeout_seconds: int = 600, retries: int | None = None) -> tuple[str | None, list[dict]]:
    """Transcribe the speech, translate it, and return (source_language, segments) with timings in seconds."""
    from google.genai import types

    client = _get_client()
    target = LANGUAGE_NAMES.get(target_language, target_language)
    prompt = (
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
    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "audio.mp3")
        _extract_audio(video_path, audio_path)
        uploaded = client.files.upload(file=audio_path, config={"mime_type": "audio/mpeg"})
        try:
            deadline = time.monotonic() + timeout_seconds
            while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
                if time.monotonic() > deadline:
                    raise TimeoutError("Gemini file processing timed out.")
                time.sleep(2)
                uploaded = client.files.get(name=uploaded.name)
            attempts = retries or int(os.getenv("GEMINI_DUB_RETRIES", "6"))
            for attempt in range(attempts):
                try:
                    response = client.models.generate_content(
                        model=MODEL,
                        contents=[uploaded, prompt],
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=SCHEMA,
                            temperature=0.2,
                        ),
                    )
                    break
                except Exception as exc:
                    err = err_l = str(exc).lower()
                    transient = any(k in err for k in ("429", "500", "503", "resource_exhausted", "unavailable", "timeout"))
                    if "per day" in err_l or "perday" in err_l:  # daily quota: retrying is pointless
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
    segments = [
        {
            "start": float(s["start"]),
            "end": float(s["end"]),
            "source_text": s.get("source_text", ""),
            "translated_text": s.get("translated_text", "").strip(),
        }
        for s in data.get("segments", [])
        if s.get("translated_text", "").strip() and float(s["end"]) > float(s["start"])
    ]
    if not segments:
        raise RuntimeError("Gemini returned no translated timed transcript segments.")
    return data.get("source_language"), segments
