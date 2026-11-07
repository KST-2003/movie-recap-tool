"""Find burned-in subtitles and static text watermarks so only those regions get blurred.

Text *detection* is language-agnostic, so this works for Chinese, Thai, Burmese and English alike.
Subtitles are text that sits at one vertical position but changes between frames; watermarks are
text that stays put and does not change.
"""
import cv2

_ocr = None


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _sample_frames(path: str, count: int):
    cap = cv2.VideoCapture(path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in range(count):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * total / count))
        ok, frame = cap.read()
        if ok:
            frames.append(frame)
    cap.release()
    return frames


def _norm(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def detect_text_regions(video_path: str, duration: float, min_conf: float = 0.45) -> dict:
    """Returns {"subtitle": rect|None, "watermarks": [rect], "texts": [str]} with rects as
    (x0, y0, x1, y1) fractions of the frame."""
    count = min(16, max(6, int(duration * 2)))
    frames = _sample_frames(video_path, count)
    if not frames:
        return {"subtitle": None, "watermarks": [], "texts": []}
    h, w = frames[0].shape[:2]
    scale = min(1.0, 960 / w)

    boxes = []  # (frame_idx, x0, y0, x1, y1, text) normalised
    for n, frame in enumerate(frames):
        small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
        result, _ = _engine()(small)
        sh, sw = small.shape[:2]
        for pts, text, conf in result or []:
            if float(conf) < min_conf or not _norm(text):
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            boxes.append((n, min(xs) / sw, min(ys) / sh, max(xs) / sw, max(ys) / sh, text))

    # Cluster boxes by vertical centre.
    clusters: list[list] = []
    for b in sorted(boxes, key=lambda b: b[2] + b[4]):
        cy = (b[2] + b[4]) / 2
        for c in clusters:
            if abs(c["cy"] - cy) < 0.03:
                c["boxes"].append(b)
                c["cy"] = sum((x[2] + x[4]) / 2 for x in c["boxes"]) / len(c["boxes"])
                break
        else:
            clusters.append({"cy": cy, "boxes": [b]})

    n_frames = len(frames)
    bands, watermarks, texts = [], [], []
    for c in clusters:
        bs = c["boxes"]
        seen = {b[0] for b in bs}
        distinct = {_norm(b[5]) for b in bs}
        x0, y0 = min(b[1] for b in bs), min(b[2] for b in bs)
        x1, y1 = max(b[3] for b in bs), max(b[4] for b in bs)
        width = sorted(b[3] - b[1] for b in bs)[len(bs) // 2]
        persistent = len(seen) / n_frames
        changing = len(distinct) >= max(2, 0.4 * len(bs))
        if changing and persistent >= 0.3 and width >= 0.15:
            bands.append((x0, y0, x1, y1, sorted(b[4] - b[2] for b in bs)[len(bs) // 2]))  # + typical text-line height
            texts += [b[5] for b in bs]
        elif not changing and persistent >= 0.7:
            watermarks.append((x0, y0, x1, y1))

    # Bilingual videos stack several subtitle bands: merge bands that sit close together into one
    # block and keep the largest block as the subtitle track.
    groups: list[list] = []
    for band in sorted(bands, key=lambda r: r[1]):
        if groups and band[1] - groups[-1][-1][3] < 0.08:
            groups[-1].append(band)
        else:
            groups.append([band])
    subtitle = None
    if groups:
        best = max(groups, key=lambda g: sum((r[2] - r[0]) * (r[3] - r[1]) for r in g))
        subtitle = (min(r[0] for r in best), min(r[1] for r in best),
                    max(r[2] for r in best), max(r[3] for r in best))
        line_height = sorted(r[4] for r in best)[len(best) // 2]   # fraction of the frame height
    else:
        line_height = None
    return {"subtitle": subtitle, "watermarks": watermarks, "texts": texts, "line_height": line_height}


def to_pixels(rect, w: int, h: int, pad_x: float = 0.03, pad_y: float = 0.012):
    """Pad a fractional rect and convert to even pixel (x, y, w, h) inside the frame."""
    x0, y0, x1, y1 = rect
    x0, x1 = max(0.0, x0 - pad_x), min(1.0, x1 + pad_x)
    y0, y1 = max(0.0, y0 - pad_y), min(1.0, y1 + pad_y)
    px, py = int(x0 * w) // 2 * 2, int(y0 * h) // 2 * 2
    pw, ph = int((x1 - x0) * w) // 2 * 2, int((y1 - y0) * h) // 2 * 2
    return px, py, max(pw, 2), max(ph, 2)
