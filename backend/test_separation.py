"""Offline check of the light speech-removal path (Spleeter ONNX, audio_tools._run_spleeter). Run: venv/bin/python test_separation.py
Skipped when the two model files are not installed (they are not in git). Checks the streaming output against a simple whole-file
computation of the same maths: same length, no glitch where the 512-frame batches join, and a short clip (one batch) works."""
import os
import sys
import tempfile
import wave

import numpy as np

import audio_tools

models = audio_tools._spleeter_models()
if not (models[0] and models[1]):
    print("SKIPPED: Spleeter models not installed")
    sys.exit(0)

import onnxruntime as ort

SR, N, HOP, F, T = 44100, 4096, 1024, 1024, 512


def reference(x):
    """Whole signal at once (x: samples x 2)."""
    x = x.T
    win = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(N) / N)).astype(np.float32)
    opts = ort.SessionOptions()          # same settings as audio_tools: where the model gives ~0 for both parts the share is
    opts.intra_op_num_threads = 1        # ill-conditioned, and another thread count changes the rounding there
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    sv, sa = (ort.InferenceSession(m, sess_options=opts, providers=["CPUExecutionProvider"]) for m in models)
    n, pad = x.shape[1], N // 2
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    frames = 1 + n // HOP
    idx = np.arange(N)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.fft.rfft(xp[:, idx] * win, axis=-1)
    res = np.zeros_like(spec)
    for a in range(0, frames, T):
        seg = spec[:, a:a + T]
        k = seg.shape[1]
        mag = np.zeros((2, 1, T, F), np.float32)
        mag[:, 0, :k] = np.abs(seg[:, :, :F])
        v = sv.run(None, {"x": mag})[0][:, 0, :k]
        acc = sa.run(None, {"x": mag})[0][:, 0, :k]
        keep = (acc ** 2 + 5e-11) / (v ** 2 + acc ** 2 + 1e-10)
        res[:, a:a + k, :F] = seg[:, :, :F] * keep
        res[:, a:a + k, F:] = seg[:, :, F:] * keep[:, :, 768:].mean(axis=2, keepdims=True)
    pieces = np.fft.irfft(res, n=N, axis=-1) * win
    y = np.zeros((2, xp.shape[1]), np.float32)
    norm = np.zeros(xp.shape[1], np.float32)
    for k in range(frames):
        y[:, k * HOP:k * HOP + N] += pieces[:, k]
        norm[k * HOP:k * HOP + N] += win ** 2
    return (y / np.maximum(norm, 1e-8))[:, pad:pad + n].T


def db(v):
    return 10 * np.log10(np.mean(np.square(v)) + 1e-15)


ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (" " + detail if detail else ""))


rng = np.random.default_rng(1)
for seconds in (30.0, 5.0):   # 30 s = three batches (two joins); 5 s = a single batch
    n = int(seconds * SR)
    t = np.arange(n) / SR
    voice = 0.3 * np.sin(2 * np.pi * (180 + 40 * np.sin(2 * np.pi * 3 * t)) * t) * (np.sin(2 * np.pi * 2 * t) > 0)
    music = 0.1 * np.sin(2 * np.pi * 440 * t) + 0.05 * rng.standard_normal(n)
    x = np.stack([voice + music, voice + 0.8 * music], axis=1).astype(np.float32)
    with tempfile.TemporaryDirectory() as d:
        raw, out = os.path.join(d, "a.f32"), os.path.join(d, "a.wav")
        x.astype("<f4").tofile(raw)
        audio_tools._run_spleeter(raw, out, models)
        with wave.open(out) as w:
            got = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, 2).astype(np.float32) / 32767
    ref = np.clip(reference(x), -1, 1)
    check(f"{seconds:.0f}s: output length equals input", len(got) == n, f"({len(got)} vs {n})")
    m = min(len(got), n)
    diff = got[:m] - ref[:m]
    check(f"{seconds:.0f}s: equals the whole-file result", db(diff) < db(ref[:m]) - 40, f"(difference {db(diff):.1f} dB, signal {db(ref[:m]):.1f} dB)")
    worst = max(db(diff[i:i + 4410]) for i in range(0, m, 4410))
    print(f"     worst 0.1 s: {worst:.1f} dB at {max(range(0, m, 4410), key=lambda i: db(diff[i:i + 4410])) / SR:.1f}s")
    for k in range(1, m // (T * HOP) + 1):
        a = k * T * HOP
        near = db(diff[a - 3000:a + 3000])
        check(f"{seconds:.0f}s: no glitch at batch join {k} ({a / SR:.1f}s)", near < db(ref[a - 3000:a + 3000]) - 40, f"(difference {near:.1f} dB)")

print("ALL PASSED" if ok else "SOME CHECKS FAILED")
sys.exit(0 if ok else 1)
