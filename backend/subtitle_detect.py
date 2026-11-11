"""Find burned-in subtitles and static text watermarks so only those regions get blurred.

Text *detection* is language-agnostic, so this works for Chinese, Thai, Burmese and English alike.
Subtitles are text that sits at one vertical position but changes between frames; watermarks are
text that stays put and does not change.
"""
import time

import cv2

_ocr = None
EARLY_STOP = 6   # frames to read before giving up when none of them contains any text


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


class _Frames:
    """`count` frames spread over the video, read ONE AT A TIME when asked (a video without any text only ever needs 6 of them).
    Fast way: ffmpeg decodes just the KEYFRAME at that time (`-skip_frame nokey`) and scales it to `width` (a 4K keyframe ~0.3 s;
    decoding a whole group of pictures was ~3 s per frame on a small server). If the keyframes are too far apart (the first
    pictures come out identical), it switches to the exact but slower OpenCV reader."""

    def __init__(self, path: str, duration: float, count: int, width: int = 960):
        self.path, self.duration, self.count, self.width = path, duration, count, width
        self.fast, self.seen, self.cap, self.cache = True, set(), None, {}

    def _fast(self, i: int):
        import hashlib
        import subprocess
        import numpy as np
        t = (i + 0.5) * self.duration / self.count
        raw = subprocess.run(["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-ss", f"{t:.3f}", "-i", self.path, "-frames:v", "1", "-an",
                              "-vf", f"scale='if(gt(iw,ih),{self.width},-2)':'if(gt(iw,ih),-2,{self.width})'", "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"],
                             capture_output=True, timeout=60).stdout
        if not raw:
            return None
        self.seen.add(hashlib.md5(raw).hexdigest())
        return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)

    def _exact(self, i: int):
        if self.cap is None:
            self.cap = cv2.VideoCapture(self.path)
        total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int((i + 0.5) * total / self.count))
        ok, frame = self.cap.read()
        return frame if ok else None

    def prepare(self, order: list):
        """Read the first 3 spread-out frames; if they are all the same picture the keyframes are too far apart: use the exact reader instead."""
        for i in order[:3]:
            self.get(i)
        if self.fast and len(self.seen) <= 1:   # none or all the same picture
            self.fast, self.cache = False, {}

    def get(self, i: int):
        if i in self.cache:
            return self.cache[i]
        frame = None
        if self.fast:
            try:
                frame = self._fast(i)
            except Exception:
                self.fast = False
        if frame is None:   # no keyframe found at that time (or the exact reader is on)
            frame = self._exact(i)
        self.cache[i] = frame
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()


def _norm(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def _recurring(boxes) -> bool:
    """True when text showed up in >= 2 different frames at about the same height (a subtitle line or a watermark does; a street sign or a
    random bit of text in one scene does not)."""
    bins: dict = {}
    for b in boxes:
        bins.setdefault(int(((b[2] + b[4]) / 2) / 0.05), set()).add(b[0])
    return any(len(frames) >= 2 for frames in bins.values())


def detect_text_regions(video_path: str, duration: float, min_conf: float = 0.45) -> dict:
    """Returns {"subtitle": rect|None, "watermarks": [rect], "texts": [str]} with rects as
    (x0, y0, x1, y1) fractions of the frame."""
    count = min(16, max(6, int(duration * 2)))
    src = _Frames(video_path, duration, count)
    t_scan = time.time()

    boxes = []  # (frame_idx, x0, y0, x1, y1, text) normalised
    order = list(range(0, count, 2)) + list(range(1, count, 2))   # evenly spread first, so a video WITHOUT any text can stop early
    done = 0
    try:
        src.prepare(order)
        for n in order:
            if done >= EARLY_STOP and not _recurring(boxes):   # 6 spread-out frames and no text that comes back at the same height: no subtitle or watermark
                break
            frame = src.get(n)
            if frame is None:
                continue
            done += 1
            scale = min(1.0, 960 / max(frame.shape[:2]))   # long side 960 px: a portrait 4K frame is ~3x fewer pixels for the OCR than 960 wide
            small = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            result, _ = _engine()(small)
            sh, sw = small.shape[:2]
            for pts, text, conf in result or []:
                if float(conf) < min_conf or not _norm(text):
                    continue
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                boxes.append((n, min(xs) / sw, min(ys) / sh, max(xs) / sw, max(ys) / sh, text, float(conf)))
    finally:
        src.close()
    print(f"  text scan: {done} frames read ({'keyframes' if src.fast else 'exact'}), {len(boxes)} text boxes, {time.time() - t_scan:.1f}s", flush=True)
    if not done:
        return {"subtitle": None, "watermarks": [], "texts": []}

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

    n_frames = done
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
            bands.append((x0, y0, x1, y1, sorted(b[4] - b[2] for b in bs)[len(bs) // 2], seen))  # + typical text-line height + frames it was seen in
            texts += [b[5] for b in bs]
        elif not changing and persistent >= 0.7:
            # a real watermark: the SAME short text at the SAME place, read with high confidence. Wide strips, mixed
            # texts or shaky readings are texture (branches, fabric...) and must not be blurred.
            frames_of = {t: {b[0] for b in bs if _norm(b[5]) == t} for t in distinct}
            stable = [t for t, fs in frames_of.items() if len(fs) >= 0.6 * n_frames and len(t) >= 2]
            same = sum(1 for b in bs if _norm(b[5]) in stable) / len(bs)
            conf = sum(b[6] for b in bs) / len(bs)
            if x1 - x0 <= 0.45 and y1 - y0 <= 0.12 and same >= 0.7 and conf >= 0.8:
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
        presence = len(set().union(*(r[5] for r in best))) / max(1, n_frames)   # share of the sampled frames that show a subtitle there
    else:
        line_height = presence = None
    return {"subtitle": subtitle, "watermarks": watermarks, "texts": texts, "line_height": line_height, "presence": presence}


def to_pixels(rect, w: int, h: int, pad_x: float = 0.03, pad_y: float = 0.012):
    """Pad a fractional rect and convert to even pixel (x, y, w, h) inside the frame."""
    x0, y0, x1, y1 = rect
    x0, x1 = max(0.0, x0 - pad_x), min(1.0, x1 + pad_x)
    y0, y1 = max(0.0, y0 - pad_y), min(1.0, y1 + pad_y)
    px, py = int(x0 * w) // 2 * 2, int(y0 * h) // 2 * 2
    pw, ph = int((x1 - x0) * w) // 2 * 2, int((y1 - y0) * h) // 2 * 2
    return px, py, max(pw, 2), max(ph, 2)


def subtitle_windows(video_path: str, duration: float, rect, step: float | None = None, stack: int = 8,
                     pad: float | None = None) -> list[tuple[float, float]] | None:
    """When is there really a subtitle in the band `rect` (fractions)? Returns merged (start, end) windows in SOURCE
    seconds, or None when the scan could not run (the caller then blurs the band the whole time).
    Samples the band only (ffmpeg crop, `1/step` fps), stacks `stack` band images into one picture and runs the text
    detector (no recognition) once per picture: ~0.04 s per sampled frame instead of 0.25 s."""
    import subprocess
    import numpy as np
    try:
        from common import display_size
        W, H = display_size(video_path)   # as shown (rotation applied): the crop below works on the rotated picture
        step = step or max(0.5, duration / 700.0)          # <= ~700 samples however long the video is
        pad = step * 0.75 if pad is None else pad
        x0, y0, x1, y1 = rect
        x0, x1 = max(0.0, x0 - 0.03), min(1.0, x1 + 0.03)
        y0, y1 = max(0.0, y0 - 0.012), min(1.0, y1 + 0.012)
        cw, ch = max(int((x1 - x0) * W) // 2 * 2, 16), max(int((y1 - y0) * H) // 2 * 2, 16)
        cap_w = 640                                              # keep the detector input small
        out_w = min(cw, cap_w) // 2 * 2
        out_h = max(int(ch * out_w / cw) // 2 * 2, 16)
        cmd = ["ffmpeg", "-loglevel", "error", "-i", video_path, "-an", "-vf",
               f"fps=1/{step:.4f},crop={cw}:{ch}:{int(x0 * W)}:{int(y0 * H)},scale={out_w}:{out_h}",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        raw = subprocess.run(cmd, capture_output=True, timeout=max(120, duration * 0.5)).stdout
        n = len(raw) // (out_w * out_h * 3)
        if n == 0:
            return None
        frames = np.frombuffer(raw[: n * out_w * out_h * 3], np.uint8).reshape(n, out_h, out_w, 3)
    except Exception as exc:
        print(f"  subtitle window scan failed ({exc})", flush=True)
        return None

    gap = 16
    present = [False] * n
    eng = _engine()
    for s in range(0, n, stack):
        group = frames[s: s + stack]
        canvas = np.zeros((len(group) * out_h + (len(group) - 1) * gap, out_w, 3), np.uint8)
        for k, fr in enumerate(group):
            canvas[k * (out_h + gap): k * (out_h + gap) + out_h] = fr
        res, _ = eng(canvas, use_det=True, use_cls=False, use_rec=False)
        for pts in res or []:
            ys = [p[1] for p in pts]
            h_box = max(ys) - min(ys)
            if h_box < out_h * 0.2:
                continue
            k = int(((max(ys) + min(ys)) / 2) // (out_h + gap))
            if 0 <= k < len(group):
                present[s + k] = True
    wins: list[list[float]] = []
    for i, ok in enumerate(present):
        if not ok:
            continue
        a, b = max(0.0, i * step - pad), min(duration, i * step + pad)
        if wins and a <= wins[-1][1] + step * 0.5:
            wins[-1][1] = b
        else:
            wins.append([a, b])
    return [(round(a, 2), round(b, 2)) for a, b in wins]
