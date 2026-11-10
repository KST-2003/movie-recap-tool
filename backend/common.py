"""Small helpers shared by the API and the workers (kept free of heavy imports)."""
import os

import gemini_tts
import subprocess

import safe_media
from safe_media import SAFE_IN
import sandbox


def media_duration(path: str) -> float:
    """Length of a media file in seconds (the server's own audio clips and the already-validated video). Protocol-restricted."""
    result = sandbox.run(
        ["ffprobe", *SAFE_IN, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        check=True,
    )
    return float(result.stdout.strip())


def upload_duration(path: str) -> float:
    """Length of a file a USER uploaded. This is the upload gate: only real video containers pass (raises safe_media.UnsafeMedia)."""
    return safe_media.inspect_video(path)["duration"]


class UserError(RuntimeError):
    """An error whose message was written FOR THE USER (no paths, vendors, keys, project ids): safe to show as it is.
    Every other exception is shown as GENERIC_ERROR and its real text goes to the server log and to the admin only."""


GENERIC_ERROR = ("Something went wrong while processing this video. Please try again. "
                 "If it keeps happening, contact support and quote this code: {ref}")


def user_message(exc: BaseException, ref: str) -> str:
    """What the user is told about a failed job. `ref` (the job id) lets support find the real error in the log / admin page."""
    if isinstance(exc, (UserError, gemini_tts.QuotaExceeded)):
        return str(exc)
    return GENERIC_ERROR.format(ref=ref)


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
