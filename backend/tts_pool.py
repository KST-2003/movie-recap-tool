"""A pool of Gemini TTS models. Every model has its OWN limits (requests per minute and per day), so several models
together give several times the capacity. One video uses ONE model from start to finish so the voice stays the same;
another model takes over mid-video only when the first one runs out of requests (last resort, the voice then changes).

- acquire(model): blocks until sending a request keeps that model under its per-minute limit; counts the daily use.
- Chooser: picks the model for a job (preference order, enough requests left today), switches when one is exhausted.
Limits come from AI Studio > Rate limits (Tier 1). Override with TTS_MODELS="name:rpm:rpd,name:rpm:rpd,..." (order = preference).
Google Cloud TTS (cloud_tts.py, names "cloud/<model>") is appended at the END of the order automatically when GCP_PROJECT_ID +
GCP_SERVICE_ACCOUNT_FILE are set: the AI Studio models are used first, Cloud takes over when they are used up (same voice names).
Counters are per process: with several worker processes each would need its own share (note for deployment)."""
import json
import math
import os
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import gemini_tts

DEFAULT_MODELS = [
    ("gemini-3.1-flash-tts-preview", 10, 100),
    ("gemini-2.5-flash-preview-tts", 10, 100),
    ("gemini-3.8-flash-tts", 10, 100),
    ("gemini-3.8-flash-lite-tts", 10, 100),
    ("gemini-2.5-pro-preview-tts", 10, 50),
]
WINDOW = 60.0     # seconds (a variable so tests can shrink it)
SAFETY = 1        # stay this many requests under the per-minute limit
USAGE_FILE = os.path.join(os.getenv("DATA_DIR", "data"), "tts_usage.json")

_lock = threading.Lock()
_recent: dict[str, deque] = {}


def models() -> list[tuple[str, int, int]]:
    """AI Studio models first (preference order), then the Google Cloud ones as extra capacity (only when Cloud is set up).
    Cloud limits are OUR soft numbers (Google's real quota is higher / adjustable): CLOUD_TTS_RPM, CLOUD_TTS_RPD."""
    import cloud_tts
    spec = os.getenv("TTS_MODELS", "").strip()
    out = []
    for part in (spec.split(",") if spec else []):
        name, rpm, rpd = (part.strip().split(":") + ["10", "100"])[:3]
        out.append((name, int(rpm), int(rpd)))
    if not spec:
        out = list(DEFAULT_MODELS)
    if cloud_tts.enabled() and not any(cloud_tts.is_cloud(n) for n, _, _ in out):
        rpm, rpd = int(os.getenv("CLOUD_TTS_RPM", "30")), int(os.getenv("CLOUD_TTS_RPD", "5000"))
        out += [(cloud_tts.PREFIX + m, rpm, rpd) for m in cloud_tts.DEFAULT_MODELS]
    import azure_tts
    if azure_tts.enabled() and not any(azure_tts.is_azure(n) for n, _, _ in out):   # last fallback, recap videos only
        out.append((azure_tts.MODEL, int(os.getenv("AZURE_TTS_RPM", "120")), int(os.getenv("AZURE_TTS_RPD", "100000"))))
    return out


_MODEL_OF: dict[str, str] = {}   # clip path -> the model that voiced it (clips of different voices must never share a cache name)


def note_model(path: str, model: str):
    if len(_MODEL_OF) > 20000:
        _MODEL_OF.clear()
    _MODEL_OF[path] = model


def model_of(path: str) -> str | None:
    return _MODEL_OF.get(path)


def usable(model: str, mode: str | None) -> bool:
    """Azure has two voices and no emotion: only for recap videos (one narrator). Full movies need many voices."""
    import azure_tts
    return mode == "recap" or not azure_tts.is_azure(model)


def _limits(model: str) -> tuple[int, int]:
    for name, rpm, rpd in models():
        if name == model:
            return rpm, rpd
    return 10, 100


def _today() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()   # Google's daily quotas reset at midnight Pacific


def _usage() -> dict:
    try:
        with open(USAGE_FILE) as f:
            data = json.load(f)
        if data.get("day") == _today():
            return data
    except Exception:
        pass
    return {"day": _today(), "counts": {}}


def used_today(model: str) -> int:
    return int(_usage()["counts"].get(model, 0))


def remaining(model: str) -> int:
    """Requests this model can still take today (0 when Google already refused it for the day)."""
    if gemini_tts.blocked_for(model) > 0:
        return 0
    return max(_limits(model)[1] - used_today(model), 0)


def reserved(model: str, exclude_job: str | None = None) -> int:
    """Requests set aside on `model` by videos that are queued or running (capacity.py stores them in Job.params; read from the
    database so API and worker processes agree). Conservative: a running video's already-used requests are counted twice."""
    from sqlalchemy import select

    from db import Job, Session
    with Session() as s:
        rows = s.execute(select(Job.id, Job.params).where(Job.status.in_(("queued", "running")))).all()
    return sum(int((p or {}).get("reserved_requests") or 0) for jid, p in rows
               if (p or {}).get("reserved_model") == model and jid != exclude_job)


def free(model: str, exclude_job: str | None = None) -> int:
    """Requests on `model` nobody has claimed (left today minus what other running videos reserved)."""
    return max(remaining(model) - reserved(model, exclude_job), 0)


def admit(need: int, mode: str | None = None) -> str | None:
    """The first model (preference order) usable for this video `mode` with `need` free requests, "" when no voice is needed,
    None when no model has room."""
    if need <= 0:
        return ""
    return next((m for m, _, _ in models() if usable(m, mode) and free(m) >= need), None)


def acquire(model: str):
    """Wait until a request to `model` stays under its per-minute limit, then count it for today."""
    rpm = max(_limits(model)[0] - SAFETY, 1)
    while True:
        with _lock:
            q = _recent.setdefault(model, deque())
            now = time.monotonic()
            while q and now - q[0] >= WINDOW:
                q.popleft()
            if len(q) < rpm:
                q.append(now)
                data = _usage()
                data["counts"][model] = data["counts"].get(model, 0) + 1
                try:
                    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
                    with open(USAGE_FILE, "w") as f:
                        json.dump(data, f)
                except OSError:
                    pass
                return
            wait = WINDOW - (now - q[0])
        time.sleep(min(max(wait, 0.05), 2.0))


def all_blocked() -> bool:
    return all(remaining(m) == 0 for m, _, _ in models())


def blocked_message() -> str:
    waits = [gemini_tts.blocked_for(m) for m, _, _ in models()]
    left = min((w for w in waits if w > 0), default=0)
    return (f"All Gemini voice models have used up their daily request limit (the first one resets in about "
            f"{int(left // 3600)}h {int(left % 3600 // 60)}m). Upgrade the Gemini tier or try again later.")


class Chooser:
    """Which TTS model a job uses. `need` = how many requests the job expects to send."""

    def __init__(self, need: int, preferred: str | None = None, job_id: str | None = None, mode: str | None = None):
        self.mode = mode   # "recap" may use Azure (last fallback); anything else may not
        self.models_used: set[str] = set()   # every model this job voiced with (a warning is shown when the voice differs)
        self.need = max(need, 1)
        self.job_id = job_id   # this job's own reservation (capacity.py) counts as free for itself
        self.switches: list[tuple[str, str]] = []   # (from, to) each time the job had to change model: the voice changes then, tell the user
        self.lock = threading.Lock()
        self.current = self._pick(preferred, ())
        self.models_used.add(self.current)
        print(f"  voice model: {self.current} ({remaining(self.current)} requests left today by our count)", flush=True)

    def _pick(self, preferred: str | None, exclude: tuple) -> str:
        order = [m for m, _, _ in models() if m not in exclude and usable(m, self.mode)]
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        avail = [m for m in order if self._free(m) > 0]
        if not avail:
            raise gemini_tts.QuotaExceeded(blocked_message())
        return next((m for m in avail if self._free(m) >= self.need), max(avail, key=self._free))

    def _free(self, model: str) -> int:
        return free(model, self.job_id)

    def get(self) -> str:
        return self.current

    def other(self, model: str) -> str | None:
        """Another model with requests left (for ONE line whose text `model` refused; the job keeps its own model)."""
        return next((m for m, _, _ in models() if m != model and usable(m, self.mode) and self._free(m) > 0), None)

    def failed(self, model: str):
        """`model` ran out of requests: switch (raises QuotaExceeded when no model is left)."""
        with self.lock:
            if self.current == model:
                self.current = self._pick(None, (model,))
                self.switches.append((model, self.current))
                self.models_used.add(self.current)
                print(f"  voice model {model} is out of requests; switching to {self.current} "
                      "(the voice of the remaining lines will differ slightly)", flush=True)
