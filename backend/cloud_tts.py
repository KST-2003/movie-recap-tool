"""Gemini voices through Google Cloud Text-to-Speech (the pool's extra capacity: Cloud has its OWN quota, separate from the
AI Studio models). Same 30 voice names, 24 kHz mono WAV. Pool names look like "cloud/gemini-2.5-flash-tts".

Needs GCP_PROJECT_ID + GCP_SERVICE_ACCOUNT_FILE (service account with the "Agent Platform User" role = roles/aiplatform.user,
and the Cloud Text-to-Speech + Agent Platform (aiplatform) APIs enabled). Turn off with CLOUD_TTS=0.
Burmese is language code my-MM. Checked against the real API on 2026-11-09 (acceptable, a little below AI Studio by ear)."""
import base64
import os
import threading

import requests

PREFIX = "cloud/"
URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
LANGUAGE = os.getenv("CLOUD_TTS_LANGUAGE", "my-MM")
DEFAULT_MODELS = ["gemini-2.5-flash-tts", "gemini-2.5-pro-tts"]   # preference order (flash: faster, as clear in the 2026-11-09 comparison)

_lock = threading.Lock()
_creds = None


def credentials_file() -> str:
    return os.getenv("GCP_SERVICE_ACCOUNT_FILE") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or ""


def project() -> str:
    return os.getenv("GCP_PROJECT_ID", "").strip()


def enabled() -> bool:
    return os.getenv("CLOUD_TTS", "1") != "0" and bool(project()) and os.path.isfile(credentials_file())


def is_cloud(model: str | None) -> bool:
    return bool(model) and model.startswith(PREFIX)


def _token() -> str:
    global _creds
    with _lock:
        if _creds is None:
            from google.oauth2 import service_account
            _creds = service_account.Credentials.from_service_account_file(
                credentials_file(), scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not _creds.valid:
            import google.auth.transport.requests as gr
            _creds.refresh(gr.Request())
        return _creds.token


def split_notes(text: str) -> tuple[str | None, str]:
    """Our director's-notes layout (looks.compose / compose_emotion) -> (style prompt, spoken text). Cloud takes the style in its own
    `prompt` field, so the notes can never be read aloud; plain text has no prompt."""
    marker = "#### TRANSCRIPT\n"
    if marker not in text:
        return None, text
    head, spoken = text.split(marker, 1)
    style = head.replace("### DIRECTOR'S NOTES", "").replace("Do not read these notes aloud.", "").strip()
    return (style or None), spoken.strip()


def synthesize(text: str, path: str, voice: str, model: str, timeout: float = 90.0) -> None:
    """Write a WAV. Failures raise RuntimeError whose text starts with the HTTP status (429 -> the caller's retry / block logic)."""
    model = model[len(PREFIX):] if is_cloud(model) else model
    style, spoken = split_notes(text)
    body = {"input": {"text": spoken, **({"prompt": style} if style else {})},
            "voice": {"languageCode": LANGUAGE, "name": voice, "modelName": model},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000}}
    r = requests.post(URL, json=body, timeout=timeout,
                      headers={"Authorization": f"Bearer {_token()}", "x-goog-user-project": project()})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} cloud tts: {r.text[:300]}")
    audio = base64.b64decode(r.json().get("audioContent", ""))
    if not audio:
        raise RuntimeError("Cloud TTS returned no audio.")
    with open(path, "wb") as f:
        f.write(audio)   # LINEAR16 already comes with a WAV header
    try:   # no token counts in Cloud's answer: estimate from the clip length (flagged in the usage record)
        import usage
        usage.record_cloud_tts(PREFIX + model, spoken, max(len(audio) - 44, 0) / 48000.0)
    except Exception:
        pass
