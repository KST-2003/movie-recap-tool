"""Fewer TTS requests: speak several sentences in ONE request, then cut the audio back into one clip per sentence.

Cutting uses the pauses the voice leaves between sentences: the N-1 longest interior silences become the cut points.
If the audio doesn't look right (too few pauses, or clip lengths far from what the text length predicts) we return
None and the caller falls back to one request per sentence, so a bad split never reaches the video."""
import os
import re
import subprocess

JOINER = os.getenv("TTS_BULK_JOINER", "\n\n")      # what separates sentences in the single request
MAX_CHARS = int(os.getenv("TTS_BULK_MAX_CHARS", "1200"))   # characters per request (tune after testing limits)
MAX_SENTENCES = int(os.getenv("TTS_BULK_MAX_SENTENCES", "8"))
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


def find_spans(path: str, texts: list[str]) -> list[tuple[float, float]] | None:
    """Return one (start, end) per sentence, or None if the split isn't trustworthy."""
    n = len(texts)
    total, silences = _silences(path)
    if n == 1:
        return [(0.0, total)]
    interior = [(a, b) for a, b in silences if a > 0.15 and b < total - 0.05]
    if len(interior) < n - 1:
        return None
    gaps = sorted(sorted(interior, key=lambda s: s[1] - s[0], reverse=True)[: n - 1])
    bounds = [0.0] + [(a + b) / 2 for a, b in gaps] + [total]
    spans = [(a, b) for a, b in zip(bounds[:-1], bounds[1:])]
    # Sanity: each clip's length should roughly follow its text length.
    chars = [max(len(t), 1) for t in texts]
    rate = total / sum(chars)
    for (a, b), c in zip(spans, chars):
        expected = rate * c
        if not (0.4 * expected <= (b - a) <= 2.5 * expected):
            return None
    return spans


def cut(path: str, spans: list[tuple[float, float]], out_paths: list[str]):
    for (a, b), out in zip(spans, out_paths):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", path, out],
                       check=True, timeout=60)


def synthesize_batch(texts: list[str], voice: str, out_paths: list[str], speak, workdir: str) -> bool:
    """`speak(text, path)` makes one audio file. Returns True when out_paths were filled from a single request."""
    joined = JOINER.join(texts)
    big = os.path.join(workdir, f"bulk_{os.getpid()}_{abs(hash(joined))}.wav")
    try:
        speak(joined, big)
        spans = find_spans(big, texts)
        if spans is None:
            return False
        cut(big, spans, out_paths)
        return True
    finally:
        if os.path.exists(big):
            os.remove(big)
