"""Small helpers shared by the API and the workers (kept free of heavy imports)."""
import json
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


def display_size(path: str) -> tuple[int, int]:
    """(width, height) of the video AS SHOWN: a phone clip is stored 3840x2160 with a "rotate 90" flag and plays 2160x3840.
    ffmpeg's filters and OpenCV both work on the rotated picture, so every pixel calculation must use this size."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate",
                          "-of", "json", path], capture_output=True, text=True, timeout=30, check=True).stdout
    st = json.loads(out)["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    rot = 0.0
    for sd in st.get("side_data_list") or []:
        if "rotation" in sd:
            rot = float(sd["rotation"])
    if not rot and (st.get("tags") or {}).get("rotate"):
        rot = float(st["tags"]["rotate"])
    return (h, w) if int(round(abs(rot))) % 180 == 90 else (w, h)


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
