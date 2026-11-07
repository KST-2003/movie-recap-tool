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


def make_soft_tone(path: str, seconds: float):
    """A quiet, slowly pulsing A-minor pad (generated, so there is no music licence to worry about)."""
    s = max(seconds, 5.0) + 2
    fc = ("[0][1][2]amix=inputs=3:normalize=0,tremolo=f=0.12:d=0.5,lowpass=f=1200,volume=0.8,"
          f"afade=t=in:d=3,afade=t=out:st={s - 3:.2f}:d=3,aformat=channel_layouts=stereo:sample_rates=44100[o]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for hz in (110.0, 164.81, 220.0):
        cmd += ["-f", "lavfi", "-i", f"sine=f={hz}:d={s:.2f}:r=44100"]
    subprocess.run(cmd + ["-filter_complex", fc, "-map", "[o]", path], check=True, timeout=120)


def mix_music(video_path: str, music_path: str, volume: float = 0.07, timeout: int = 600):
    """Add a quiet music track under the finished video's audio. Video stream is copied (seconds, not minutes)."""
    tmp = video_path + ".music.mp4"
    fc = (f"[1:a]volume={volume:.3f}[m];[0:a]aformat=channel_layouts=stereo:sample_rates=44100[a0];"
          "[a0][m]amix=inputs=2:normalize=0:duration=first[a]")
    res = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-i", music_path, "-filter_complex", fc,
                          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", tmp],
                         capture_output=True, timeout=timeout)
    if res.returncode != 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(res.stderr.decode(errors="replace")[-500:])
    os.replace(tmp, video_path)
