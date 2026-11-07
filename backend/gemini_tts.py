"""Gemini text-to-speech (Google AI Studio API key). Output is a 24 kHz mono WAV file."""
import base64
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")  # Flash-Lite does not support Burmese
DEFAULT_VOICE = os.getenv("GEMINI_VOICE", "Kore")
# Optional delivery instruction put before the text, e.g. "Read as an energetic, engaging movie-recap narrator:".
# Off by default: if the model reads it aloud it would ruin every clip. Compare with test_tts_style.py first.
STYLE = os.getenv("TTS_STYLE", "").strip()
_client = None
BLOCK_FILE = os.path.join(os.getenv("DATA_DIR", "data"), "tts_blocked.json")  # shared by API and worker processes


class QuotaExceeded(RuntimeError):
    """Gemini's daily request limit is used up. Retrying only wastes time: stop the job, refuse new ones."""


def _blocks() -> dict:
    try:
        with open(BLOCK_FILE) as f:
            data = json.load(f)
        return data if "until" not in data else {}
    except Exception:
        return {}


def blocked_for(model: str | None = None) -> float:
    """Seconds until this model's daily voice limit resets (0 when requests may be sent). Each model has its own limit."""
    return max(0.0, _blocks().get(model or MODEL, 0) - time.time())


def _block(error_text: str, model: str | None = None):
    m = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", error_text)
    secs = (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0
    try:
        os.makedirs(os.path.dirname(BLOCK_FILE), exist_ok=True)
        blocks = _blocks()
        blocks[model or MODEL] = time.time() + (secs or 3600)
        with open(BLOCK_FILE, "w") as f:
            json.dump(blocks, f)
    except OSError:
        pass


def quota_message(model: str | None = None) -> str:
    left = blocked_for(model)
    return (f"The Gemini voice service's daily request limit is used up (resets in about {int(left // 3600)}h "
            f"{int(left % 3600 // 60)}m). Upgrade the Gemini tier or try again later.")
# The SDK's own HTTP timeout did not stop a voice request that never answered, so every request runs in a pool thread
# and we stop waiting after a deadline we control (the hung thread is abandoned; we retry on a fresh one).
_pool = ThreadPoolExecutor(max_workers=64, thread_name_prefix="tts")


def _deadline(text: str) -> float:
    """Seconds to wait for one request: a few sentences take 10-20 s; scale with length, bounded."""
    return float(os.getenv("GEMINI_TTS_REQUEST_TIMEOUT", "0")) or min(150.0, 40.0 + len(text) / 15.0)


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


def synthesize_to_file(text: str, path: str, voice: str | None = None, retries: int = 3, model: str | None = None) -> None:
    voice = voice or DEFAULT_VOICE
    model = model or MODEL
    if blocked_for(model) > 0:
        raise QuotaExceeded(quota_message(model))
    last: Exception | None = None
    for attempt in range(retries):
        try:
            import tts_pool
            tts_pool.acquire(model)   # stay under this model's per-minute limit (and count today's use)
            started = time.monotonic()
            client = _get_client()
            future = _pool.submit(lambda: client.interactions.create(
                model=model,
                input=f"{STYLE}\n\n{text}" if STYLE else text,
                response_format={"type": "audio"},
                generation_config={"speech_config": [{"voice": voice}]},
            ))
            try:
                interaction = future.result(timeout=_deadline(text))
            except FutureTimeout:
                raise TimeoutError(f"timeout: no answer from Gemini TTS after {_deadline(text):.0f}s") from None
            print(f"  TTS ok: {len(text)} chars in {time.monotonic() - started:.1f}s", flush=True)
            audio = interaction.output_audio
            if audio is None or not audio.data:
                raise RuntimeError("Gemini returned no audio.")
            pcm = base64.b64decode(audio.data)
            if pcm[:4] != b"RIFF":  # some models (2.5, 3.1) return bare 24 kHz 16-bit mono samples: add the WAV header
                import wave
                with wave.open(path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm)
            else:
                with open(path, "wb") as f:
                    f.write(pcm)
            return
        except Exception as exc:
            last = exc
            text_err = err_l = str(exc).lower()
            transient = any(k in text_err for k in ("429", "500", "503", "resource_exhausted", "unavailable", "timeout", "too_many_requests"))
            if "per day" in err_l or "perday" in err_l:  # daily quota: retrying is pointless
                _block(str(exc), model)
                raise QuotaExceeded(quota_message(model)) from exc
            if not transient or attempt == retries - 1:
                break
            print(f"  Gemini TTS slow/busy ({exc.__class__.__name__}: {str(exc)[:120]}); retry {attempt + 1}/{retries - 1}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini TTS failed: {last}") from last
