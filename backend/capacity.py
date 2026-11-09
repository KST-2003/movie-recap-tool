"""Admission control: a video is only STARTED when there is room to finish it, so a burst of uploads cannot start 20 videos
that then all fail half way when the money or the voice quota runs out.

Two checks, made in one place under a lock together with creating the job (main.create_job):
 1. MONEY (optional, set in the admin dashboard): the owner types what is left in the Google billing account. Every video charges
    its minutes at upload (charged_seconds, refunded when it fails), so `spent = charged minutes since the balance was typed x
    cost per minute` already includes videos still running. Refused unless the free budget covers this video AND at least
    `min_free_minutes` of video (default 30) - that buffer is never handed out.
 2. VOICE REQUESTS: the video's estimated TTS requests are RESERVED on ONE voice model (the first with enough requests left after the
    other running videos' reservations). The reservation is stored in the job's params (Job.params.reserved_*), counts while the job is
    queued/running, and disappears when it finishes - so it works across API and worker processes. The job then keeps that model
    from start to finish (same voice). Switching model mid-video stays only as a last resort.
Refused -> HTTP 503 with BUSY_MESSAGE, and the owner is alerted (alerts.py). All numbers are estimates: type the real balance again
whenever you top up or check Google billing."""
import math
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import func, select

import alerts
import tts_pool
from admin import settings as S
from common import tts_provider
from db import Job

BUSY_MESSAGE = "The server is currently busy. We have notified the admin. Please try again later."
REQUESTS_PER_VIDEO_MINUTE = float(os.getenv("TTS_REQUESTS_PER_VIDEO_MINUTE", "6"))   # voice requests incl. fit rounds (estimate: ~55 for 10 min)
REQUESTS_BASE = 4
lock = threading.Lock()


def est_requests(seconds: float, output: str | None) -> int:
    if tts_provider() != "gemini" or output == "subtitles":
        return 0
    return math.ceil(seconds / 60 * REQUESTS_PER_VIDEO_MINUTE) + REQUESTS_BASE


def measured_cost_per_minute(s) -> float | None:
    """Real THB per charged video minute over the last 30 finished videos whose cost is fully priced (None before 3 such videos)."""
    import usage
    table, rate = usage.prices(), S.usd_thb()
    rows = s.execute(select(Job.charged_seconds, Job.data).where(Job.status == "done", Job.charged_seconds > 0)
                     .order_by(Job.finished_at.desc()).limit(30)).all()
    cost = minutes = 0.0
    n = 0
    for charged, data in rows:
        c = usage.cost_thb((data or {}).get("usage"), table, rate)
        if (data or {}).get("usage") and c["complete"]:
            cost, minutes, n = cost + c["thb"], minutes + charged / 60, n + 1
    return cost / minutes if n >= 3 and minutes > 0 else None


def spent_thb(s, since) -> tuple[float, int, int]:
    """THB used since `since`: the REAL token cost where a video's usage is fully priced (also for failed videos: tokens were paid),
    else the estimate (charged minutes x cost per minute, measured when available). Videos still running count at least their estimate.
    -> (thb, videos priced from tokens, videos estimated)"""
    import usage
    table, rate = usage.prices(), S.usd_thb()
    per_min = measured_cost_per_minute(s) or S.cost_per_minute_thb()
    total, real, est_n = 0.0, 0, 0
    for status, charged, data in s.execute(select(Job.status, Job.charged_seconds, Job.data).where(Job.created_at >= since)).all():
        estimate = (charged or 0.0) / 60 * per_min
        c = usage.cost_thb((data or {}).get("usage"), table, rate) if (data or {}).get("usage") else None
        actual = c["thb"] if c and c["complete"] else None
        if status in ("queued", "running"):
            total += max(estimate, c["thb"] if c else 0.0)   # unfinished: keep room for the whole video
            est_n += 1
        elif actual is not None:
            total, real = total + actual, real + 1
        elif status == "done":
            total, est_n = total + max(estimate, c["thb"] if c else 0.0), est_n + 1
        elif c:
            total += c["thb"]   # failed / cancelled: whatever was priced
    return total, real, est_n


def budget(s) -> dict:
    """Money view: {enabled, balance_thb, spent_thb, left_thb, cost_per_minute, available_minutes, min_free_minutes}."""
    configured, floor = S.cost_per_minute_thb(), S.min_free_minutes()
    measured = measured_cost_per_minute(s)
    cost = measured or configured
    out = {"enabled": S.budget_enabled(), "cost_per_minute": round(cost, 3), "cost_per_minute_measured": round(measured, 3) if measured else None,
           "min_free_minutes": floor}
    if not out["enabled"]:
        return out
    since = datetime.fromisoformat(S.budget_set_at()) if S.budget_set_at() else datetime(2000, 1, 1, tzinfo=timezone.utc)
    spent, real, est_n = spent_thb(s, since)
    balance = S.budget_thb()
    left = balance - spent
    return {**out, "balance_thb": balance, "spent_thb": round(spent, 1), "left_thb": round(left, 1),
            "available_minutes": round(max(left, 0) / cost, 1) if cost > 0 else 0.0, "set_at": S.budget_set_at(),
            "videos_priced_from_tokens": real, "videos_estimated": est_n}


def decide(s, seconds: float, output: str | None) -> dict:
    """-> {"ok": True, "model": str, "requests": int} or {"ok": False, "reason": str}. Call under `lock`, add the job before releasing it."""
    minutes = seconds / 60
    b = budget(s)
    if b["enabled"] and b["available_minutes"] < max(b["min_free_minutes"], minutes):
        return {"ok": False, "reason": (f"Budget: {b['available_minutes']:.0f} video minutes left in the voice/AI budget "
                                        f"(at least {max(b['min_free_minutes'], minutes):.0f} needed for this video).")}
    need = est_requests(seconds, output)
    model = tts_pool.admit(need)
    if model is None:
        return {"ok": False, "reason": (f"Voice capacity: no voice model has {need} free requests left for this video "
                                        f"(counting videos already running).")}
    return {"ok": True, "model": model, "requests": need}


def refuse(reason: str):
    """Tell the owner and raise the 503 the user sees."""
    from fastapi import HTTPException
    alerts.raise_alert("capacity", f"A video was refused because the server is out of capacity. {reason}")
    raise HTTPException(status_code=503, detail=BUSY_MESSAGE)


def status(s) -> dict:
    """For the admin Overview: money + voice capacity right now."""
    b = budget(s)
    models = [{"model": m, "left": tts_pool.remaining(m), "reserved": tts_pool.reserved(m), "free": tts_pool.free(m)} for m, _, _ in tts_pool.models()]
    low = bool(b["enabled"] and b["available_minutes"] < 3 * b["min_free_minutes"])
    return {"budget": b, "voice": models, "voice_free_requests": sum(m["free"] for m in models), "low": low}
