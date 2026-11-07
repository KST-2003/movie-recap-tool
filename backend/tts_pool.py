"""A pool of Gemini TTS models. Every model has its OWN limits (requests per minute and per day), so several models
together give several times the capacity. One video uses ONE model from start to finish so the voice stays the same;
another model takes over mid-video only when the first one runs out of requests (last resort, the voice then changes).

- acquire(model): blocks until sending a request keeps that model under its per-minute limit; counts the daily use.
- Chooser: picks the model for a job (preference order, enough requests left today), switches when one is exhausted.
Limits come from AI Studio > Rate limits (Tier 1). Override with TTS_MODELS="name:rpm:rpd,name:rpm:rpd,..." (order = preference).
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
    spec = os.getenv("TTS_MODELS", "").strip()
    if not spec:
        return DEFAULT_MODELS
    out = []
    for part in spec.split(","):
        name, rpm, rpd = (part.strip().split(":") + ["10", "100"])[:3]
        out.append((name, int(rpm), int(rpd)))
    return out


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

    def __init__(self, need: int, preferred: str | None = None):
        self.need = max(need, 1)
        self.lock = threading.Lock()
        self.current = self._pick(preferred, ())
        print(f"  voice model: {self.current} ({remaining(self.current)} requests left today by our count)", flush=True)

    def _pick(self, preferred: str | None, exclude: tuple) -> str:
        order = [m for m, _, _ in models() if m not in exclude]
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        avail = [m for m in order if remaining(m) > 0]
        if not avail:
            raise gemini_tts.QuotaExceeded(blocked_message())
        return next((m for m in avail if remaining(m) >= self.need), max(avail, key=remaining))

    def get(self) -> str:
        return self.current

    def failed(self, model: str):
        """`model` ran out of requests: switch (raises QuotaExceeded when no model is left)."""
        with self.lock:
            if self.current == model:
                self.current = self._pick(None, (model,))
                print(f"  voice model {model} is out of requests; switching to {self.current} "
                      "(the voice of the remaining lines will differ slightly)", flush=True)
