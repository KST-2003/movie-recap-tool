"""Gemini text-to-speech (Google AI Studio API key). Output is a 24 kHz mono WAV file."""
import base64
import os
import time

MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")  # Flash-Lite does not support Burmese
DEFAULT_VOICE = os.getenv("GEMINI_VOICE", "Kore")
# Optional delivery instruction put before the text, e.g. "Read as an energetic, engaging movie-recap narrator:".
# Off by default: if the model reads it aloud it would ruin every clip. Compare with test_tts_style.py first.
STYLE = os.getenv("TTS_STYLE", "").strip()
_client = None


def available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        # A hung request must fail (and retry) instead of freezing a job forever.
        # attempts=1: the SDK's own retry can sleep for the server's whole "retry in 16h" hint and look like a hang.
        # We retry transient errors ourselves (short, bounded) and fail fast on quota errors.
        _client = genai.Client(http_options=types.HttpOptions(
            timeout=int(os.getenv("GEMINI_HTTP_TIMEOUT_MS", "60000")),
            retry_options=types.HttpRetryOptions(attempts=1)))  # reads GEMINI_API_KEY / GOOGLE_API_KEY
    return _client


def synthesize_to_file(text: str, path: str, voice: str | None = None, retries: int = 3) -> None:
    voice = voice or DEFAULT_VOICE
    last: Exception | None = None
    for attempt in range(retries):
        try:
            interaction = _get_client().interactions.create(
                model=MODEL,
                input=f"{STYLE}\n\n{text}" if STYLE else text,
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice}]},
            )
            audio = interaction.output_audio
            if audio is None or not audio.data:
                raise RuntimeError("Gemini returned no audio.")
            with open(path, "wb") as f:
                f.write(base64.b64decode(audio.data))
            return
        except Exception as exc:
            last = exc
            text_err = err_l = str(exc).lower()
            transient = any(k in text_err for k in ("429", "500", "503", "resource_exhausted", "unavailable", "timeout", "too_many_requests"))
            if "per day" in err_l or "perday" in err_l:  # daily quota: retrying is pointless
                transient = False
            if not transient or attempt == retries - 1:
                break
            print(f"  Gemini TTS slow/busy ({exc.__class__.__name__}: {str(exc)[:120]}); retry {attempt + 1}/{retries - 1}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini TTS failed: {last}") from last
