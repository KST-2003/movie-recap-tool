"""Speaking pitch (F0) from audio, numpy only. Used to (1) check a character's gender label against the ORIGINAL voice and
(2) notice when an emotional TTS clip drifted away from its character's normal voice (e.g. a male voice turning female)."""
import subprocess

import numpy as np

SR = 16000


def load(path: str, start: float | None = None, dur: float | None = None) -> np.ndarray:
    """Any audio/video file -> mono float32 at 16 kHz (via ffmpeg)."""
    cmd = ["ffmpeg", "-loglevel", "error"] + (["-ss", f"{start:.3f}"] if start else []) + (["-t", f"{dur:.3f}"] if dur else []) + \
          ["-i", path, "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, timeout=300).stdout, np.float32)


def f0_frames(x: np.ndarray, fmin: float = 70.0, fmax: float = 350.0) -> np.ndarray:
    """F0 of every clearly voiced 50 ms frame (20 ms hop), in Hz (FFT autocorrelation, all frames at once).
    Whispers and noise are not periodic, so they are skipped."""
    n, hop = int(0.05 * SR), int(0.02 * SR)
    lo, hi = int(SR / fmax), int(SR / fmin)
    if len(x) < n * 2:
        return np.array([])
    idx = np.arange(0, len(x) - n, hop)
    frames = np.stack([x[i: i + n] for i in idx]).astype(np.float64)
    frames -= frames.mean(axis=1, keepdims=True)
    frames *= np.hanning(n)
    energy = np.sqrt((frames ** 2).mean(axis=1))
    spec = np.fft.rfft(frames, 2 * n, axis=1)
    ac = np.fft.irfft(spec * np.conj(spec), axis=1)[:, : hi + 1]
    ac0 = ac[:, 0] + 1e-12
    k = np.argmax(ac[:, lo: hi + 1], axis=1) + lo
    peak = ac[np.arange(len(k)), k] / ac0
    gate = max(np.percentile(energy, 90) * 0.35, 1e-5)
    ok = (peak >= 0.5) & (energy >= gate)
    return SR / k[ok]


def f0_median(x: np.ndarray) -> tuple[float | None, int]:
    f = f0_frames(x)
    return (float(np.median(f)) if len(f) >= 15 else None), len(f)


_ref: dict[str, float | None] = {}


def voice_reference(voice: str) -> float | None:
    """Normal pitch of a Gemini voice, measured once from its sample file (voice_samples/<voice>.wav)."""
    import os
    if voice not in _ref:
        path = os.path.join("voice_samples", f"{voice}.wav")
        _ref[voice] = f0_median(load(path))[0] if os.path.exists(path) else None
    return _ref[voice]


def drifted(path: str, voice: str, lo: float = 0.78, hi: float = 1.28) -> tuple[bool, float | None, float | None]:
    """Did the clip leave its voice's normal pitch range (about +-4 semitones)? A male voice turning female is ~1.5x.
    Returns (drifted, clip_f0, voice_f0); (False, ...) when either pitch cannot be measured."""
    ref = voice_reference(voice)
    got = f0_median(load(path))[0]
    if not ref or not got:
        return False, got, ref
    return not (lo <= got / ref <= hi), got, ref
