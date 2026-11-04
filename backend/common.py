"""Small helpers shared by the API and the workers (kept free of heavy imports)."""
import os
import subprocess

import gemini_tts


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


def tts_provider() -> str:
    """TTS_PROVIDER=gemini|elevenlabs; default is Gemini when a Google key is present."""
    choice = os.getenv("TTS_PROVIDER", "").lower()
    if choice in ("gemini", "elevenlabs", "fake"):  # fake = tone generator for tests / load tests
        return choice
    return "gemini" if gemini_tts.available() else "elevenlabs"


def dub_provider() -> str:
    """DUB_PROVIDER=local|elevenlabs|gemini; default is local (faster-whisper + NLLB, no API)."""
    choice = os.getenv("DUB_PROVIDER", "local").lower()
    return choice if choice in ("local", "elevenlabs", "gemini") else "local"


def audio_ext() -> str:
    return ".mp3" if tts_provider() == "elevenlabs" else ".wav"
