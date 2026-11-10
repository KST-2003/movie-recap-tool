"""Settings the admin dashboard can change while the server runs (no restart, shared by API and worker processes through a
small JSON file next to the database). A value that was never set falls back to the environment default in config.py."""
import json
import os
import threading

from datetime import datetime, timezone

from config import DATA_DIR, GLOBAL_DAILY_MINUTES, KEEP_RESULT_DAYS, KEEP_SOURCE_DAYS, MAINTENANCE_MODE

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


# Money budget (see capacity.py): the owner types what is left in the Google billing account (THB) and what one video minute costs.
def budget_enabled() -> bool:
    d = _load()
    return bool(d.get("budget_enabled")) and d.get("budget_thb") is not None


def budget_thb() -> float:
    return float(_load().get("budget_thb") or 0.0)


def budget_set_at() -> str | None:
    return _load().get("budget_set_at")


def cost_per_minute_thb() -> float:
    value = _load().get("cost_per_minute_thb")
    return float(os.getenv("COST_PER_MINUTE_THB", "1.0")) if value is None else float(value)


def cost_per_minute_standard_thb() -> float:
    """Standard (Azure) voice: used until 3 finished videos give a measured value."""
    value = _load().get("cost_per_minute_standard_thb")
    return float(os.getenv("COST_PER_MINUTE_STANDARD_THB", "1.0")) if value is None else float(value)


def min_free_minutes() -> float:
    value = _load().get("min_free_minutes")
    return float(os.getenv("MIN_FREE_MINUTES", "30")) if value is None else float(value)


def keep_result_days() -> float:
    value = _load().get("keep_result_days")
    return KEEP_RESULT_DAYS if value is None else float(value)


def keep_source_days() -> float:
    value = _load().get("keep_source_days")
    return KEEP_SOURCE_DAYS if value is None else float(value)


def video_crf() -> int:
    """x264 quality of rendered videos: lower = sharper and bigger/slower (18 near lossless ... 28 small). 23 = ffmpeg's default."""
    value = _load().get("video_crf")
    return int(os.getenv("VIDEO_CRF", "23")) if value is None else int(value)


# Pay as you go: the user buys video minutes (packs), pays by QR + slip, the admin approves.
DEFAULT_PACKS = [30, 60, 100, 200]


def price_per_minute_thb() -> float:
    value = _load().get("price_per_minute_thb")
    return float(os.getenv("PRICE_PER_MINUTE_THB", "5")) if value is None else float(value)


def topup_packs() -> list[int]:
    value = _load().get("topup_packs")
    return [int(m) for m in value] if isinstance(value, list) and value else list(DEFAULT_PACKS)


def payment_note() -> str:
    return str(_load().get("payment_note") or "")


def payment_qr_file() -> str | None:
    return _load().get("payment_qr_file") or None


def usd_thb() -> float:
    value = _load().get("usd_thb")
    return float(os.getenv("USD_THB", "35")) if value is None else float(value)   # check the real rate: it only converts Google's USD prices


def prices() -> dict:
    """Owner-edited USD prices per 1M tokens: {model: {"in","audio_in","out","audio_out"}} (overrides usage.DEFAULT_PRICES)."""
    value = _load().get("prices")
    return value if isinstance(value, dict) else {}


def update(**changes) -> dict:
    """Persist the given settings (None removes an override so the environment default applies again)."""
    with _lock:
        data = _load()
        if changes.get("budget_thb") is not None:   # typing the balance starts a new count of what was spent since
            changes["budget_set_at"] = datetime.now(timezone.utc).isoformat()
        for key, value in changes.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        tmp = _FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _FILE)
    return view()


def view() -> dict:
    return {"maintenance": maintenance(), "global_daily_minutes": global_daily_minutes(), "budget_enabled": budget_enabled(),
            "budget_thb": _load().get("budget_thb"), "budget_set_at": budget_set_at(), "cost_per_minute_thb": cost_per_minute_thb(), "cost_per_minute_standard_thb": cost_per_minute_standard_thb(),
            "min_free_minutes": min_free_minutes(), "usd_thb": usd_thb(),
            "keep_result_days": keep_result_days(), "keep_source_days": keep_source_days(), "video_crf": video_crf(),
            "price_per_minute_thb": price_per_minute_thb(), "topup_packs": topup_packs(), "payment_note": payment_note(), "payment_qr_file": payment_qr_file()}
