"""Azure Neural TTS: the pool's LAST fallback, for RECAP videos only (one narrator).
Burmese has just two Azure voices (my-MM-NilarNeural female, my-MM-ThihaNeural male), so a Gemini voice is mapped by gender
(Kore -> Nilar, Charon -> Thiha). No emotion / character directions (they are dropped), so it is never used for full movies (see
tts_pool: mode). Chosen because it is accepted for recap (owner listened, 2026-11-10: clear, constant voice) and has very high
throughput (default 200 requests/s on S0; checked: 12 parallel requests in 1.4 s, heard-back clarity 0.98-1.00).
Needs AZURE_SPEECH_KEY + AZURE_SPEECH_REGION (server side only; never in the frontend or git). AZURE_TTS=0 turns it off.
Pool name: "azure/neural". Billed per CHARACTER (usage.py "chars")."""
import os
from xml.sax.saxutils import escape

import requests

PREFIX = "azure/"
MODEL = "azure/neural"
FEMALE_VOICE = os.getenv("AZURE_VOICE_FEMALE", "my-MM-NilarNeural")
MALE_VOICE = os.getenv("AZURE_VOICE_MALE", "my-MM-ThihaNeural")


def key() -> str:
    return os.getenv("AZURE_SPEECH_KEY", "").strip()


def region() -> str:
    return os.getenv("AZURE_SPEECH_REGION", "").strip()


def enabled() -> bool:
    return os.getenv("AZURE_TTS", "1") != "0" and bool(key()) and bool(region())


def is_azure(model: str | None) -> bool:
    return bool(model) and model.startswith(PREFIX)


def azure_voice(gemini_voice: str | None) -> str:
    """Gemini voice name -> the Azure voice of the same gender (no voice / "su" = the default, a female voice)."""
    from voices import MALE
    return MALE_VOICE if gemini_voice in MALE else FEMALE_VOICE


def build_ssml(spoken: str, voice: str) -> str:
    return (f'<speak version="1.0" xml:lang="my-MM" xmlns="http://www.w3.org/2001/10/synthesis">'
            f'<voice name="{voice}">{escape(spoken)}</voice></speak>')


def synthesize(text: str, path: str, gemini_voice: str | None, timeout: float = 60.0) -> None:
    """Write a 24 kHz mono WAV. Errors raise RuntimeError starting with the HTTP status (429 / 5xx are retried by the caller)."""
    from cloud_tts import split_notes
    _, spoken = split_notes(text)   # style / emotion notes are not supported here: only the spoken text
    r = requests.post(f"https://{region()}.tts.speech.microsoft.com/cognitiveservices/v1",
                      data=build_ssml(spoken, azure_voice(gemini_voice)).encode("utf-8"), timeout=timeout,
                      headers={"Ocp-Apim-Subscription-Key": key(), "Content-Type": "application/ssml+xml",
                               "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} azure tts: {r.text[:200]}")
    with open(path, "wb") as f:
        f.write(r.content)
    try:
        import usage
        usage.record_azure(MODEL, len(spoken))
    except Exception:
        pass
