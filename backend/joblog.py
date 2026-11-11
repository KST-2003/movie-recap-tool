"""Per-video log: everything the pipeline prints (stage START/DONE lines, timings, ffmpeg/OCR notes, TTS lines) is also kept
with the video, so the admin can read it in the job detail page (like the server's console output, but for one video).
How: stdout/stderr are wrapped once; a line printed by a thread that belongs to a job (usage.py's context variable, which the
worker threads inherit) is appended to that job's buffer. update_job() saves the buffer into Job.data["log"] (throttled)."""
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone

import usage

MAX_LINES = 600      # per video (the newest ones are kept)
MAX_LINE = 300       # characters per line
_buffers: dict[str, deque] = {}
_dirty: dict[str, float] = {}      # job id -> time of the last save
_lock = threading.Lock()
_installed = False


def add(job_id: str, line: str):
    line = line.rstrip()
    if not line:
        return
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with _lock:
        buf = _buffers.setdefault(job_id, deque(maxlen=MAX_LINES))
        buf.append(f"{stamp} {line[:MAX_LINE]}")
        _dirty.setdefault(job_id, 0.0)


class _Tee:
    def __init__(self, real):
        self._real, self._partial = real, {}

    def write(self, text):
        n = self._real.write(text)
        try:
            job_id = usage.current()
            if job_id and text:
                part = self._partial.get(threading.get_ident(), "") + text
                *lines, rest = part.split("\n")
                self._partial[threading.get_ident()] = rest
                for ln in lines:
                    add(job_id, ln)
        except Exception:
            pass   # logging must never break a video
        return n

    def __getattr__(self, name):
        return getattr(self._real, name)


def install():
    global _installed
    if _installed:
        return
    _installed = True
    sys.stdout = _Tee(sys.stdout)
    sys.stderr = _Tee(sys.stderr)


def pending(job_id: str, force: bool = False, every: float = 5.0):
    """The lines to save now (None = nothing new, or saved less than `every` seconds ago)."""
    with _lock:
        if job_id not in _buffers or job_id not in _dirty:
            return None
        if not force and time.time() - _dirty[job_id] < every:
            return None
        _dirty[job_id] = time.time()
        return list(_buffers[job_id])


def forget(job_id: str):
    with _lock:
        _buffers.pop(job_id, None)
        _dirty.pop(job_id, None)
