"""Visual scene-cut detection (ffmpeg). The cut times are given to Gemini as a hint and used to snap segment starts."""
import re
import subprocess

THRESHOLD = 0.35  # 0..1, higher = only hard cuts


BIG_PIXELS = 1920 * 1080 * 1.2   # above this (4K phone clips) every frame is not worth decoding just to find the cuts
# Decoding every frame costs about (pixels x seconds). A 10-minute 1080x1912 film took ~5 MINUTES on the capped server CPU (while OCR shared it)
# and held back the whole job. Past this much work only keyframes are read (x264 puts a keyframe on most hard cuts).
MAX_DECODE_WORK = 1280 * 720 * 150   # = a 2.5-minute 720p clip, or 70 s of 1080p


def _duration(video_path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def _skip_args(video_path: str) -> list[str]:
    """Large pictures or long videos: look at the KEYFRAMES only (~15x cheaper than decoding every frame).
    The cuts are only a hint for the transcript and for snapping segment starts, so a missed cut costs little."""
    try:
        from common import display_size
        w, h = display_size(video_path)
        return ["-skip_frame", "nokey"] if w * h > BIG_PIXELS or w * h * _duration(video_path) > MAX_DECODE_WORK else []
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
