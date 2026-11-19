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


def real_media_duration(path: str, timeout: float = 90.0) -> float | None:
    """How long the file REALLY is: the end of its last packet (sound and picture), not the length written in its header.

    `media_duration` believes the container header, which the uploader controls: a Matroska/WebM file whose Duration element says 1 s but
    holds 30 s is billed 1 s (security audit 2026-11-19, finding 2). This reads the packet list instead (no decoding, a few seconds for a
    1 GB file). The list is streamed line by line and only the maximum is kept, so a hostile file with millions of packets cannot fill the
    memory, and the whole scan has a wall-clock limit. Returns None when the length cannot be read in time or at all: the caller must then
    treat the file as unverified (main.enforce_real_length cuts it to the billed length)."""
    import threading
    import time
    deadline = time.monotonic() + timeout
    best = 0.0
    found = False
    for stream in ("a:0", "v:0"):
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        proc = subprocess.Popen(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", stream,
             "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        timed_out = threading.Event()

        def _stop(p=proc, flag=timed_out):   # a watchdog: ffprobe that stalls without printing cannot block a line read for ever
            flag.set()
            p.kill()
        watchdog = threading.Timer(left, _stop)
        watchdog.start()
        try:
            for line in proc.stdout:
                parts = line.strip().split(",")
                try:
                    end = float(parts[0]) + (float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 0.0)
                except (ValueError, IndexError):
                    continue
                found = True
                if end > best:
                    best = end
        finally:
            watchdog.cancel()
            proc.kill()
            proc.wait()
        if timed_out.is_set():
            return None
    return best if found else None


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
