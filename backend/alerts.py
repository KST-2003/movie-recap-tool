"""Things the owner must know about (e.g. uploads refused because the budget or voice capacity is used up).
Stored in data/admin_alerts.json (shared by API and workers), shown on the admin Overview, and - only if ADMIN_WEBHOOK_URL is set -
sent to a chat webhook (Slack / Discord / Telegram-bridge style: JSON {"text": ..., "content": ...}), at most once per hour per kind."""
import json
import os
import threading
import time

import requests

from config import DATA_DIR

_FILE = os.path.join(DATA_DIR, "admin_alerts.json")
_lock = threading.Lock()
WEBHOOK_EVERY = 3600       # seconds between messages of the same kind
SHOW_FOR = 24 * 3600       # an alert stays on the Overview for a day after its last refusal


def _load() -> dict:
    try:
        with open(_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict):
    try:
        os.makedirs(os.path.dirname(_FILE), exist_ok=True)
        with open(_FILE + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(_FILE + ".tmp", _FILE)
    except OSError:
        pass


def _send(message: str):
    url = os.getenv("ADMIN_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        requests.post(url, json={"text": message, "content": message}, timeout=5)
    except Exception as exc:   # a broken webhook must never break an upload
        print(f"[alerts] webhook failed: {exc}", flush=True)


def raise_alert(kind: str, message: str) -> None:
    now = time.time()
    with _lock:
        data = _load()
        a = data.get(kind) or {}
        if now - a.get("last_at", 0) > SHOW_FOR:   # an old alert starts over
            a = {"first_at": now, "count": 0}
        a.update(last_at=now, message=message, count=a.get("count", 0) + 1)
        send = now - a.get("sent_at", 0) >= WEBHOOK_EVERY
        if send:
            a["sent_at"] = now
        data[kind] = a
        _save(data)
    print(f"[alert] {kind}: {message}", flush=True)
    if send:
        threading.Thread(target=_send, args=(f"Movie Recap Tool: {message}",), daemon=True).start()


def active() -> list[dict]:
    now = time.time()
    return [{"kind": k, **v} for k, v in _load().items() if now - v.get("last_at", 0) <= SHOW_FOR]
