"""Source-audio helpers: split the original track so music/effects can be kept under the new voice."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import wave


def _spleeter_models() -> tuple[str, str]:
    configured = os.getenv("SPLEETER_MODEL_DIR")
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [configured] if configured else []
    candidates += [os.path.join(here, "models", "spleeter"),
                   "/var/www/movie-recap/models/spleeter",
                   os.path.join(here, "..", "frontend", "public", "models", "spleeter")]
    for folder in candidates:
        if folder:
            vocals = os.path.join(folder, "vocals.onnx")
            accompaniment = os.path.join(folder, "accompaniment.onnx")
            if os.path.isfile(vocals) and os.path.isfile(accompaniment):
                return vocals, accompaniment
    return "", ""


def separation_available() -> bool:
    """True when either the light ONNX model or optional Demucs is ready to use."""
    if os.getenv("SEPARATION_PROVIDER", "auto").lower() == "off":
        return False
    provider = os.getenv("SEPARATION_PROVIDER", "auto").lower()
    models = _spleeter_models()
    spleeter_ready = bool(models[0] and models[1] and importlib.util.find_spec("onnxruntime")
                          and importlib.util.find_spec("numpy"))
    demucs_ready = bool(importlib.util.find_spec("demucs"))
    if provider == "spleeter":
        return spleeter_ready
    if provider == "demucs":
        return demucs_ready
    return spleeter_ready or demucs_ready


def _read_audio(video_path: str, raw_path: str, timeout: int = 300) -> int:
    """Decode to little-endian float32 stereo 44.1 kHz; return sample frames."""
    with open(raw_path, "wb") as raw:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-vn",
                        "-ac", "2", "-ar", "44100", "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"],
                       stdout=raw, check=True, timeout=timeout)
    size = os.path.getsize(raw_path)
    if size < 8 or size % 8:
        raise RuntimeError("Could not decode the source audio as stereo PCM")
    return size // 8


def _run_spleeter(src_raw: str, result: str, model_paths: tuple[str, str]) -> None:
    """Run the sherpa-onnx Spleeter 2-stem models in bounded inference batches."""
    import numpy as np
    import onnxruntime as ort

    # Keep CPU use predictable on the small shared production server.
    options = ort.SessionOptions()
    options.intra_op_num_threads = max(1, int(os.getenv("SPLEETER_THREADS", "1")))
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sessions = [ort.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])
                for path in model_paths]
    for session in sessions:
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        if not inputs or not outputs:
            raise RuntimeError("Spleeter ONNX model has no input or output")

    audio = np.memmap(src_raw, dtype="<f4", mode="r", shape=(os.path.getsize(src_raw) // 8, 2))
    total = len(audio)
    # This is the same 44.1 kHz / 4096 FFT / 1024 hop / 512 frame model path used by
    # deviceSeparateLight.js. Only one 512-frame inference batch is materialized at a time.
    n_fft, hop, bins, frames_per_batch = 4096, 1024, 1024, 512
    pad = n_fft // 2
    frame_count = 1 + total // hop
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n_fft, dtype=np.float64) / n_fft)).astype(np.float32)
    # Ring buffers only retain the current inference batch and its FFT overlap. This keeps
    # working memory independent of film length (the decoded input itself is memory-mapped).
    ring_size = frames_per_batch * hop + n_fft
    acc = np.zeros((2, ring_size), dtype=np.float32)
    norm = np.zeros(ring_size, dtype=np.float32)
    channels = [audio[:, 0], audio[:, 1]]
    feed_name = sessions[0].get_inputs()[0].name

    # Reflection at both ends avoids adding zero-padding clicks.
    def reflected(index):
        if total < 2:
            return np.zeros_like(index)
        period = 2 * (total - 1)
        index = np.mod(index, period)
        return np.where(index < total, index, period - index)

    frame_offsets = np.arange(n_fft, dtype=np.int64)[None, :]
    win_sq = window * window
    with wave.open(result, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(44100)
        for first in range(0, frame_count, frames_per_batch):
            count = min(frames_per_batch, frame_count - first)
            offsets = (first + np.arange(count, dtype=np.int64))[:, None] * hop
            indices = reflected(offsets + frame_offsets - pad)
            spectra = np.empty((2, frames_per_batch, n_fft // 2 + 1), dtype=np.complex64)
            magnitudes = np.zeros((2, 1, frames_per_batch, bins), dtype=np.float32)
            for channel in range(2):
                block = np.asarray(channels[channel][indices], dtype=np.float32)
                block *= window
                spec = np.fft.rfft(block, n=n_fft, axis=1).astype(np.complex64)
                spectra[channel, :count] = spec
                magnitudes[channel, 0, :count] = np.abs(spec[:, :bins])
            vocals = sessions[0].run([sessions[0].get_outputs()[0].name], {feed_name: magnitudes})[0]
            accompaniment = sessions[1].run([sessions[1].get_outputs()[0].name],
                                             {sessions[1].get_inputs()[0].name: magnitudes})[0]
            # Preserve the original mixture's phase and apply the model's accompaniment share.
            keep = (accompaniment * accompaniment + 5e-11) / (vocals * vocals + accompaniment * accompaniment + 1e-10)
            for channel in range(2):
                mask = keep[channel, 0, :count]
                high = np.mean(mask[:, 768:], axis=1, keepdims=True)
                full_mask = np.concatenate((mask, np.repeat(high, n_fft // 2 + 1 - bins, axis=1)), axis=1)
                reconstructed = np.fft.irfft(spectra[channel, :count] * full_mask, n=n_fft, axis=1).astype(np.float32)
                for j in range(count):
                    start = j * hop
                    acc[channel, start:start + n_fft] += reconstructed[j] * window
            for j in range(count):
                start = j * hop
                norm[start:start + n_fft] += win_sq

            # Ring index r is sample first*hop + r - pad. After this batch everything below count*hop is complete
            # (later frames start there); the pad samples after it still get the next batch's first frames, so they
            # are written with the NEXT batch (writing them now left a small glitch every 11.9 s).
            last = first + count >= frame_count
            lo = pad if first == 0 else 0
            hi = min(total + pad - first * hop, ring_size) if last else count * hop
            if hi > lo:
                denom = np.maximum(norm[lo:hi], 1e-8)
                interleaved = np.stack((acc[0, lo:hi] / denom, acc[1, lo:hi] / denom), axis=1)
                pcm = np.clip(interleaved * 32767.0, -32768, 32767).astype("<i2")
                wav.writeframesraw(pcm.tobytes())
            if not last:
                shift = count * hop
                acc[:, :-shift] = acc[:, shift:]
                acc[:, -shift:] = 0
                norm[:-shift] = norm[shift:]
                norm[-shift:] = 0

    del audio, acc, norm, sessions


def separate_background(video_path: str, work_dir: str, tag: str, timeout: int = 1800) -> str:
    """Return stereo music/effects with speech reduced (Spleeter ONNX; Demucs fallback)."""
    work_dir = os.path.abspath(work_dir)
    provider = os.getenv("SEPARATION_PROVIDER", "auto").lower()
    models = _spleeter_models()
    if provider not in ("demucs", "off") and models[0] and models[1] \
            and importlib.util.find_spec("onnxruntime") and importlib.util.find_spec("numpy"):
        src = os.path.join(work_dir, f"{tag}_spleeter.f32")
        result = os.path.join(work_dir, f"{tag}_spleeter.wav")
        try:
            _read_audio(video_path, src)
            _run_spleeter(src, result, models)
            return result
        finally:
            if os.path.exists(src):
                os.remove(src)
    if provider == "spleeter":
        raise RuntimeError("Spleeter was selected but its ONNX runtime or model files are missing")
    if provider == "off" or not importlib.util.find_spec("demucs"):
        raise RuntimeError("No speech-separation model is installed (need Spleeter ONNX models or Demucs)")

    src = os.path.join(work_dir, f"{tag}_srcaudio.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-vn", "-ac", "2", "-ar", "44100", src],
                   check=True, timeout=300)
    out_dir = os.path.join(work_dir, f"{tag}_demucs")
    res = subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", out_dir, src],
                         capture_output=True, text=True, timeout=timeout)
    result = os.path.join(out_dir, "htdemucs", f"{tag}_srcaudio", "no_vocals.wav")
    os.remove(src)
    if res.returncode != 0 or not os.path.isfile(result):
        raise RuntimeError(f"Demucs failed: {res.stderr[-500:]}")
    return result


def cleanup_separation(work_dir: str, tag: str):
    for path in (os.path.join(os.path.abspath(work_dir), f"{tag}_demucs"),
                 os.path.join(os.path.abspath(work_dir), f"{tag}_spleeter.wav")):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)


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
