"""Visual scene-cut detection (ffmpeg). The cut times are given to Gemini as a hint and used to snap segment starts."""
import re
import subprocess
from safe_media import SAFE_IN

THRESHOLD = 0.35  # 0..1, higher = only hard cuts


def detect_cuts(video_path: str, threshold: float = THRESHOLD, timeout: int = 600) -> list[float]:
    """Times (seconds) where the picture changes sharply. Runs on a tiny downscaled copy so it is fast."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", *SAFE_IN, "-i", video_path, "-an", "-vf",
         f"fps=12,scale=160:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, timeout=timeout,
    )
    cuts = sorted({round(float(t), 2) for t in re.findall(r"pts_time:([\d.]+)", proc.stderr)})
    return cuts


def snap(t: float, cuts: list[float], tolerance: float = 0.3) -> float:
    """Move t onto the nearest cut if one is within `tolerance` seconds."""
    best = min(cuts, key=lambda c: abs(c - t), default=None)
    return best if best is not None and abs(best - t) <= tolerance else t
