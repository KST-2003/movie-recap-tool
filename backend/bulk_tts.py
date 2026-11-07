"""Fewer TTS requests: speak several sentences in ONE request, then cut the audio back into one clip per sentence.

Cutting uses the pauses the voice leaves between sentences: the N-1 longest interior silences become the cut points.
If the audio doesn't look right (too few pauses, or clip lengths far from what the text length predicts) we return
None and the caller falls back to one request per sentence, so a bad split never reaches the video."""
import os
import re
import subprocess

import numpy as np

import duration_model

JOINER = os.getenv("TTS_BULK_JOINER", "\n\n")      # what separates sentences in the single request
MAX_CHARS = int(os.getenv("TTS_BULK_MAX_CHARS", "1800"))   # characters per request (tune after testing limits)
MAX_SENTENCES = int(os.getenv("TTS_BULK_MAX_SENTENCES", "12"))
MIN_GAP = float(os.getenv("TTS_BULK_MIN_GAP", "0.18"))     # seconds of silence that can count as a sentence break
SILENCE_DB = os.getenv("TTS_BULK_SILENCE_DB", "-38")


def make_batches(texts: list[str]) -> list[list[int]]:
    """Indices of consecutive sentences grouped under the request limits."""
    batches, cur, chars = [], [], 0
    for i, t in enumerate(texts):
        if cur and (chars + len(t) > MAX_CHARS or len(cur) >= MAX_SENTENCES):
            batches.append(cur)
            cur, chars = [], 0
        cur.append(i)
        chars += len(t)
    if cur:
        batches.append(cur)
    return batches


def _silences(path: str) -> tuple[float, list[tuple[float, float]]]:
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", f"silencedetect=noise={SILENCE_DB}dB:d={MIN_GAP}", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    total = 0.0
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", proc.stderr)
    if m:
        total = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    if len(starts) > len(ends):  # silence that runs to the end of the file
        ends.append(total)
    return total, list(zip(starts, ends))


def _envelope(path: str, hop: float = 0.01) -> np.ndarray:
    """Loudness in dB every `hop` seconds (so index * hop = time)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, timeout=120, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(8000 * hop)
    frames = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-5)


def find_spans(path: str, texts: list[str], model: dict | None = None) -> list[tuple[float, float]] | None:
    """One (start, end) per sentence, or None if the split isn't trustworthy.

    Candidate cut points are the clearly quiet stretches of the audio (>= 0.12 s, far below speech level). All
    boundaries are chosen together (dynamic programming): the set whose clip lengths best match the duration model's
    prediction for each sentence, rewarding longer pauses. (Taking the N-1 longest pauses, or the quietest spot near
    each expected boundary, both picked word gaps on real Gemini audio.)"""
    n = len(texts)
    hop = 0.01
    env = _envelope(path, hop)
    total = len(env) * hop
    if n == 1:
        return [(0.0, total)]
    pred = np.array([duration_model.predict(t, model) for t in texts])
    pred *= total / pred.sum()  # the model supplies proportions only; they must add up to this audio
    smooth = np.convolve(env, np.ones(5) / 5, mode="same")
    quiet = np.where(smooth < np.percentile(env, 75) - 12)[0]
    runs = [r for r in np.split(quiet, np.where(np.diff(quiet) > 1)[0] + 1) if len(r) >= 12]
    cands = [(((r[0] + r[-1]) / 2) * hop, len(r) * hop) for r in runs]
    cands = [(t, ln) for t, ln in cands if 0.4 < t < total - 0.3]
    if len(cands) < n - 1:
        return None
    times = np.array([0.0] + [t for t, _ in cands] + [total])
    reward = np.array([0.0] + [min(ln, 0.7) / 0.7 for _, ln in cands] + [0.0])
    m = len(times)
    MU = 0.6
    INF = 1e9
    best = np.full((n + 1, m), INF)   # best[k][j]: cost with k sentences placed, k-th boundary at candidate j
    back = np.zeros((n + 1, m), dtype=int)
    best[0][0] = 0.0
    for k in range(1, n + 1):
        for j in range(1, m):
            if k < n and j == m - 1:
                continue
            if k == n and j != m - 1:
                continue
            for i in range(m):
                if best[k - 1][i] >= INF or times[i] >= times[j] - 0.3:
                    continue
                ratio = (times[j] - times[i]) / pred[k - 1]
                if not 0.5 <= ratio <= 1.9:
                    continue
                cost = best[k - 1][i] + (ratio - 1) ** 2 - (MU * reward[j] if k < n else 0.0)
                if cost < best[k][j]:
                    best[k][j], back[k][j] = cost, i
    if best[n][m - 1] >= INF:
        return None
    idx, j = [m - 1], m - 1
    for k in range(n, 0, -1):
        j = back[k][j]
        idx.append(j)
    t = times[idx[::-1]]
    return [(float(a), float(c)) for a, c in zip(t[:-1], t[1:])]


def cut(path: str, spans: list[tuple[float, float]], out_paths: list[str]):
    for (a, b), out in zip(spans, out_paths):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", path, out],
                       check=True, timeout=60)


def synthesize_batch(texts: list[str], voice: str, out_paths: list[str], speak, workdir: str,
                     model: dict | None = None) -> bool:
    """`speak(text, path)` makes one audio file. Returns True when out_paths were filled from a single request."""
    joined = JOINER.join(texts)
    big = os.path.join(workdir, f"bulk_{os.getpid()}_{abs(hash(joined))}.wav")
    try:
        speak(joined, big)
        spans = find_spans(big, texts, model)
        if spans is None:
            return False
        cut(big, spans, out_paths)
        return True
    finally:
        if os.path.exists(big):
            os.remove(big)
