"""Predict how long the TTS voice takes to read a Burmese line, without calling the TTS.

duration ~= a * syllables + b      (a = seconds per syllable, b = fixed lead/trail overhead of a clip)

Syllables are counted as Myanmar consonants that are not stacked (after virama U+1039) and not killed (before asat U+103A).
On real Gemini clips this tracks length well (corr 0.89; worst error ~0.6 s on 3 s clips). The coefficients are
re-fitted per job from that job's own (text, duration) pairs, so each voice/speed calibrates itself; the defaults only
matter for the first few lines. The same formula is used in the browser editor (frontend/src/Editor.jsx)."""
import numpy as np

DEFAULT = {"a": 0.16, "b": 0.7}  # seconds per syllable, clip overhead (from the 8-sentence Gemini test)
STOPS = "။၊"


def syllables(text: str) -> int:
    n = 0
    for i, c in enumerate(text):
        if 0x1000 <= ord(c) <= 0x1021 and (i == 0 or text[i - 1] != "္") and not (i + 1 < len(text) and text[i + 1] == "်"):
            n += 1
        elif 0x1023 <= ord(c) <= 0x1027:  # independent vowels
            n += 1
    if n == 0:  # not Burmese (English / numbers): about 1 syllable per 3 letters
        n = max(1, round(sum(ch.isalnum() for ch in text) / 3))
    return n


def predict(text: str, model: dict | None = None) -> float:
    m = model or DEFAULT
    return m["a"] * syllables(text) + m["b"]


def fit(pairs: list[tuple[str, float]], prior: dict | None = None) -> dict:
    """Least-squares (a, b) from (text, seconds) pairs, pulled toward the prior when there are few samples."""
    prior = prior or DEFAULT
    pairs = [(t, d) for t, d in pairs if t.strip() and d > 0.2]
    if len(pairs) < 6:
        return dict(prior)
    x = np.array([syllables(t) for t, _ in pairs], float)
    y = np.array([d for _, d in pairs], float)
    xs = np.concatenate([x, [x.mean()] * 2])
    ys = np.concatenate([y, [prior["a"] * x.mean() + prior["b"]] * 2])
    a, b = np.polyfit(xs, ys, 1) if x.std() > 0.5 else (prior["a"], y.mean() - prior["a"] * x.mean())
    a = float(np.clip(a, 0.05, 0.3))
    b = float(np.clip(y.mean() - a * x.mean(), 0.0, 1.5))
    return {"a": round(a, 4), "b": round(b, 3)}
