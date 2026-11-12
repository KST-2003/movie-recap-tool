"""Rough "about X minutes left" for a running video.

Two estimates of the video's TOTAL run time are blended:
1. from history: recent finished videos of the same kind took `ratio` x their length (median), so this one should take
   ratio x its length (defaults until 2 such videos exist);
2. from this video's own speed: it reached progress p after t seconds, and at p a video is normally a known share of the way
   through (`share`), so total = t / share. The share of the time spent before the render starts is learned from history too.
The further the video is, the more the second one counts. Remaining = total - elapsed. When the video already runs longer
than the estimate, `over` is set and the UI says it is taking longer than usual instead of showing a wrong number.

Pure functions (no database): `main._job_view` passes the rows. Tested by test_eta.py."""
from datetime import datetime
from statistics import median

# progress value -> share of the total run time that has normally passed when it is first reached (server render)
DEFAULT_CURVE = [(0, 0.0), (3, 0.02), (10, 0.20), (35, 0.38), (60, 0.48), (68, 0.58), (75, 0.60), (100, 1.0)]
RENDER_AT = 75
DEFAULT_RATIO = {"render": 0.9, "device": 0.6, "subtitles": 0.5, "edit": 0.4}   # run seconds per video second
MIN_HISTORY = 2


def kind_of(params: dict) -> str:
    if params.get("edit"):
        return "edit"
    if params.get("output") == "subtitles":
        return "subtitles"
    return "device" if params.get("device_render") else "render"


def _ts(at) -> float | None:
    try:
        return datetime.fromisoformat(at).timestamp()
    except (TypeError, ValueError):
        return None


def _first_reach(stages: list, started: float, progress: int) -> float | None:
    """Seconds after the start at which `progress` (or more) was first reported."""
    for st in stages or []:
        if (st.get("progress") or 0) >= progress:
            t = _ts(st.get("at"))
            return max(t - started, 0.0) if t else None
    return None


def learn(history: list[dict], kind: str) -> dict:
    """history: finished videos, each {kind, seconds (video length), run_seconds, started_at, stages}.
    -> {ratio or None, render_share or None, n}."""
    rows = [h for h in history if h.get("kind") == kind and (h.get("run_seconds") or 0) > 0]
    ratios = [h["run_seconds"] / h["seconds"] for h in rows if (h.get("seconds") or 0) > 5]
    shares = []
    for h in rows:
        if h.get("started_at"):
            t = _first_reach(h.get("stages"), h["started_at"], RENDER_AT)
            if t is not None and 0.05 < t / h["run_seconds"] < 0.98:
                shares.append(t / h["run_seconds"])
    return {"ratio": median(ratios) if len(ratios) >= MIN_HISTORY else None,
            "render_share": median(shares) if len(shares) >= MIN_HISTORY else None,
            "runs": median([h["run_seconds"] for h in rows]) if len(rows) >= MIN_HISTORY else None, "n": len(rows)}


def share_at(progress: float, render_share: float | None = None) -> float:
    """Share of the total run time normally passed when `progress` is reached."""
    p = min(max(progress, 0), 100)
    base = DEFAULT_CURVE[-1][1]
    for (p0, f0), (p1, f1) in zip(DEFAULT_CURVE, DEFAULT_CURVE[1:]):
        if p <= p1:
            base = f0 + (f1 - f0) * (p - p0) / (p1 - p0)
            break
    if render_share is None:
        return base
    d = dict(DEFAULT_CURVE)[RENDER_AT]
    if p <= RENDER_AT:
        return base / d * render_share
    return render_share + (1 - render_share) * (p - RENDER_AT) / (100 - RENDER_AT)


def estimate(params: dict, seconds: float, started_at: float | None, progress: int, stages: list, history: list[dict],
             now: float) -> dict | None:
    """-> {"eta_seconds": int, "over": bool} or None when nothing sensible can be said yet."""
    if not started_at:
        return None
    kind = kind_of(params)
    elapsed = max(now - started_at, 0.0)
    known = learn(history, kind)

    by_history = None
    if seconds and seconds > 5:
        by_history = (known["ratio"] or DEFAULT_RATIO[kind]) * seconds + 20
    elif known["runs"]:
        by_history = known["runs"]            # an edit: its length is not charged, use what such jobs usually take

    by_speed, share = None, share_at(progress, known["render_share"])
    reached = _first_reach([s for s in stages or [] if (s.get("progress") or 0) == progress], started_at, progress)
    if reached is not None and share >= 0.12 and reached > 3:
        by_speed = reached / share

    if by_history is None and by_speed is None:
        return None
    if by_speed is None:
        total = by_history
    elif by_history is None:
        total = by_speed
    else:
        w = min(share * 1.5, 0.9)             # late in the video its own speed is the better guide
        total = (1 - w) * by_history + w * by_speed
    left = total - elapsed
    return {"eta_seconds": int(max(left, 0)), "over": left < 5}
