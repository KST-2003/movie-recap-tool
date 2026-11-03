"""Source-audio helpers: split the original track so music/effects can be kept under the new voice."""
import os
import subprocess
import sys


def separate_background(video_path: str, work_dir: str, tag: str, timeout: int = 1800) -> str:
    """Return the path of a stereo music+effects track with the original voice removed (Demucs)."""
    work_dir = os.path.abspath(work_dir)
    src = os.path.join(work_dir, f"{tag}_srcaudio.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-vn", "-ac", "2", "-ar", "44100", src],
                   check=True, timeout=300)
    out_dir = os.path.join(work_dir, f"{tag}_demucs")
    res = subprocess.run(
        [sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", out_dir, src],
        capture_output=True, text=True, timeout=timeout)
    result = os.path.join(out_dir, "htdemucs", f"{tag}_srcaudio", "no_vocals.wav")
    os.remove(src)
    if res.returncode != 0 or not os.path.isfile(result):
        raise RuntimeError(f"Demucs failed: {res.stderr[-500:]}")
    return result


def cleanup_separation(work_dir: str, tag: str):
    import shutil
    shutil.rmtree(os.path.join(os.path.abspath(work_dir), f"{tag}_demucs"), ignore_errors=True)
