"""Visual scene-cut detection (ffmpeg). The cut times are given to Gemini as a hint and used to snap segment starts."""
import re
import subprocess

THRESHOLD = 0.35  # 0..1, higher = only hard cuts


BIG_PIXELS = 1920 * 1080 * 1.2   # above this (4K phone clips) every frame is not worth decoding just to find the cuts


def _skip_args(video_path: str) -> list[str]:
    """Large pictures: look at the KEYFRAMES only (encoders put a keyframe at most hard cuts; ~15x cheaper than decoding every 4K frame).
    The cuts are only a hint for the transcript and for snapping segment starts, so a missed cut costs little."""
    try:
        from common import display_size
        w, h = display_size(video_path)
        return ["-skip_frame", "nokey"] if w * h > BIG_PIXELS else []
    except Exception:
        return []


def detect_cuts(video_path: str, threshold: float = THRESHOLD, timeout: int = 600) -> list[float]:
    """Times (seconds) where the picture changes sharply. Runs on a tiny downscaled copy so it is fast."""
    keyframes_only = _skip_args(video_path)
    vf = f"scale=160:-2,select='gt(scene,{threshold})',showinfo" if keyframes_only else f"fps=12,scale=160:-2,select='gt(scene,{threshold})',showinfo"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", *keyframes_only, "-i", video_path, "-an", "-vf", vf, "-f", "null", "-"],
        capture_output=True, text=True, timeout=timeout,
    )
    cuts = sorted({round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)})
    return cuts


def snap(t: float, cuts: list[float], tolerance: float = 0.3) -> float:
    """Move t onto the nearest cut if one is within `tolerance` seconds."""
    best = min(cuts, key=lambda c: abs(c - t), default=None)
    return best if best is not None and abs(best - t) <= tolerance else t
