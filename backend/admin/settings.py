"""Settings the admin dashboard can change while the server runs (no restart, shared by API and worker processes through a
small JSON file next to the database). A value that was never set falls back to the environment default in config.py."""
import json
import os
import threading

from config import DATA_DIR, GLOBAL_DAILY_MINUTES, MAINTENANCE_MODE

_FILE = os.path.join(DATA_DIR, "admin_settings.json")
_lock = threading.Lock()


def _load() -> dict:
    try:
        with open(_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def maintenance() -> bool:
    value = _load().get("maintenance")
    return MAINTENANCE_MODE if value is None else bool(value)


def global_daily_minutes() -> float:
    value = _load().get("global_daily_minutes")
    return GLOBAL_DAILY_MINUTES if value is None else float(value)


def update(**changes) -> dict:
    """Persist the given settings (None removes an override so the environment default applies again)."""
    with _lock:
        data = _load()
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        tmp = _FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _FILE)
    return {"maintenance": maintenance(), "global_daily_minutes": global_daily_minutes()}
