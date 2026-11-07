"""Timeline-based sync engine for dubbed recap videos.

The dubbed audio drives the timeline: each source scene is stretched (slowed or
frozen) until its translated voice-over fits, so audio, video and captions stay
aligned no matter how long the translation runs.
"""
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace

from PIL import Image, ImageDraw, ImageFont

BREATH = 0.10  # silence kept after each voice clip so clips never run together
MIN_SCENE = 0.05

# NotoSansMyanmar.ttc index of the Bold face; the other candidates are single-face files.
FONT_CANDIDATES = [
    (os.getenv("BURMESE_FONT_PATH", ""), 0),
    ("/System/Library/Fonts/NotoSansMyanmar.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Myanmar Sangam MN.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansMyanmar-Bold.ttf", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansMyanmar-Regular.ttf", 0),
    ("C:/Windows/Fonts/mmrtext.ttf", 0),
]


@dataclass
class SyncOptions:
    allow_speedup: bool = False  # speed up voice (up to max_speedup) before slowing video
    max_speedup: float = 1.15
    min_video_speed: float = 0.7  # slowest the video may play before freezing the last frame


@dataclass
class EffectOptions:
    blur_subtitles: bool = False
    blur_watermark: bool = False
    flip_h: bool = False
    flip_v: bool = False
    speed: float = 1.0
    brightness: float = 0.0  # -1..1
    contrast: float = 1.0  # 0..2
    saturation: float = 1.0  # 0..3
    logo_path: str | None = None
    logo_width_frac: float = 0.15
    logo_position: str = "top-right"
    captions: bool = True
    subtitle_rect: tuple | None = None  # pixel (x, y, w, h) of detected source subtitles; None = nothing to blur
    watermark_rects: list = field(default_factory=list)  # detected static-text watermarks, pixel rects
    background_path: str | None = None  # separated music/effects track to keep under the new voice
    background_volume: float = 0.35
    duck_background: bool = False     # lower the background track while the new voice speaks (sidechain compression)
    source_audio: bool = False        # no dubbing: keep the video's own audio (subtitles-only mode)
    caption_px: int | None = None     # caption font size in px (set from the original subtitle height); None = default


@dataclass
class Scene:
    src_start: float
    src_end: float
    video_speed: float = 1.0
    freeze: float = 0.0
    out_len: float = 0.0
    audio_index: int | None = None  # index into the segment list
    tempo: float = 1.0
    audio_len: float = 0.0  # voice length after tempo
    text: str = ""
    out_start: float = 0.0
    action: str = "natural"


def plan_timeline(segments: list[dict], video_duration: float, opts: SyncOptions) -> list[Scene]:
    """segments: dicts with start, translated_text, audio_dur (sorted or not)."""
    order = sorted(range(len(segments)), key=lambda i: segments[i]["start"])
    starts, kept = [], []
    for i in order:
        s = min(max(0.0, segments[i]["start"]), video_duration)
        if starts and s <= starts[-1] + MIN_SCENE:
            continue  # collapse near-duplicate starts; keep the earlier segment
        starts.append(s)
        kept.append(i)

    scenes: list[Scene] = []
    if not kept or starts[0] > MIN_SCENE:
        lead_end = starts[0] if kept else video_duration
        scenes.append(Scene(0.0, lead_end, out_len=lead_end))
    elif kept:
        starts[0] = 0.0

    for n, i in enumerate(kept):
        src_start = starts[n]
        src_end = starts[n + 1] if n + 1 < len(kept) else video_duration
        slot = max(src_end - src_start, MIN_SCENE)
        dur = float(segments[i]["audio_dur"])
        sc = Scene(src_start, src_end, audio_index=i, text=segments[i]["translated_text"])

        tempo = 1.0
        manual = segments[i].get("tempo")  # editor override: fixed voice speed for this line
        if manual:
            tempo = min(max(float(manual), 0.7), 1.6)
        elif opts.allow_speedup and dur + BREATH > slot:
            tempo = min(opts.max_speedup, dur / max(slot - BREATH, 0.1))
            tempo = max(tempo, 1.0)
        audio_len = dur / tempo
        need = audio_len + BREATH

        speed, new_len, freeze = 1.0, slot, 0.0
        if need > slot:
            speed = max(opts.min_video_speed, slot / need)
            new_len = slot / speed
            if need > new_len:
                freeze = need - new_len
        sc.tempo, sc.audio_len = tempo, audio_len
        sc.video_speed, sc.freeze = speed, freeze
        sc.out_len = new_len + freeze
        sc.action = "natural" if need <= slot else ("slow" if freeze == 0 else "slow+freeze")
        if tempo > 1.0:
            sc.action = "speedup" if need <= slot / speed else sc.action + "+speedup"
        scenes.append(sc)

    t = 0.0
    for sc in scenes:
        sc.out_start = t
        t += sc.out_len
    return scenes


# ---------- captions ----------

FALLBACK_FONTS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_fallback(size: int):
    for path in FALLBACK_FONTS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _is_myanmar(ch: str) -> bool:
    return "\u1000" <= ch <= "\u109f" or "\ua9e0" <= ch <= "\ua9ff" or "\uaa60" <= ch <= "\uaa7f"


def _runs(text: str):
    """Split into (text, is_myanmar) runs; spaces and punctuation stay with the preceding run."""
    runs: list[list] = []
    for ch in text:
        kind = _is_myanmar(ch) if ch.isalnum() or _is_myanmar(ch) else (runs[-1][1] if runs else True)
        if runs and runs[-1][1] == kind:
            runs[-1][0] += ch
        else:
            runs.append([ch, kind])
    return [(t, k) for t, k in runs]


class Fonts:
    """Myanmar face with a Latin/digit fallback; the Myanmar font has no Latin glyphs."""

    def __init__(self, size: int):
        self.size = size
        self.main = _load_font(size)
        self.alt = _load_fallback(size)
        try:
            self.ascent, self.descent = self.main.getmetrics()
        except AttributeError:
            self.ascent, self.descent = size, size // 4

    def width(self, draw, text: str) -> float:
        return sum(draw.textlength(t, font=self.main if my else self.alt) for t, my in _runs(text))

    def draw(self, draw, x: float, baseline: float, text: str):
        for t, my in _runs(text):
            font = self.main if my else self.alt
            draw.text((x, baseline), t, font=font, anchor="ls", fill=(255, 235, 59, 255),
                      stroke_width=1, stroke_fill=(0, 0, 0, 255))
            x += draw.textlength(t, font=font)


def _load_font(size: int):
    for path, index in FONT_CANDIDATES:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size, index=index, layout_engine=ImageFont.Layout.RAQM)
            except Exception:
                try:
                    return ImageFont.truetype(path, size, index=index)
                except Exception:
                    continue
    return ImageFont.load_default()


def _is_base(ch: str) -> bool:
    # Safe break points inside unspaced Burmese: before a consonant/independent vowel, never before a mark.
    return "\u1000" <= ch <= "\u1021" or ch in " \u104a\u104b"


def _wrap(draw, text: str, fonts: "Fonts", max_w: int) -> list[str]:
    def width(s):
        return fonts.width(draw, s)

    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if width(trial) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
            cur = ""
        if width(word) <= max_w:
            cur = word
            continue
        for ch in word:  # unspaced run longer than a line: break on base letters
            if width(cur + ch) > max_w and cur and _is_base(ch):
                lines.append(cur)
                cur = ""
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def render_caption(text: str, path: str, width: int, height: int, max_lines: int = 3, size_px: int | None = None):
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    size = max(int(width * 0.05), 18)
    if size_px:  # match the original subtitle (slightly bigger), within sane bounds
        size = int(min(max(size_px, width * 0.035), width * 0.075))
    max_w = int(width * 0.88)
    while True:
        fonts = Fonts(size)
        lines = _wrap(draw, text, fonts, max_w)
        line_h = int((fonts.ascent + fonts.descent) * 1.12) + 6
        if (len(lines) <= max_lines and len(lines) * line_h <= height - 16) or size <= 16:
            break
        size -= 2
    total_h = len(lines) * line_h
    y = height - total_h - 8
    for line in lines:
        tw = fonts.width(draw, line)
        x = (width - tw) / 2
        draw.rounded_rectangle([x - 14, y + 2, x + tw + 14, y + line_h - 2], radius=8, fill=(0, 0, 0, 150))
        fonts.draw(draw, x, y + 3 + fonts.ascent * 1.06, line)
        y += line_h
    img.save(path)


def _split_sentences(text: str, min_chars: int = 12) -> list[str]:
    """Split on sentence enders (Burmese ။, . ! ? and CJK equivalents); fold tiny pieces into a neighbour."""
    parts = [p.strip() for p in re.findall(r"[^။.!?！？。]+[။.!?！？。]*", text) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    if len(merged) > 1 and len(merged[-1]) < min_chars:
        tail = merged.pop()
        merged[-1] = f"{merged[-1]} {tail}"
    return merged or [text.strip()]


def caption_cues(scenes: list[Scene], speed: float) -> list[tuple[float, float, str]]:
    """One cue per sentence; each scene's speech time is shared out by sentence length."""
    cues = []
    for sc in scenes:
        if sc.audio_index is None or not sc.text.strip():
            continue
        start = sc.out_start / speed
        end = (sc.out_start + sc.audio_len + BREATH / 2) / speed
        sentences = _split_sentences(sc.text)
        total = sum(len(x) for x in sentences) or 1
        t = start
        for n, sentence in enumerate(sentences):
            e = end if n == len(sentences) - 1 else t + (end - start) * len(sentence) / total
            cues.append((t, e, sentence))
            t = e
    return cues


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues, path: str):
    with open(path, "w", encoding="utf-8") as f:
        for n, (a, b, text) in enumerate(cues, 1):
            f.write(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n\n")


def build_caption_track(cues, total_len: float, work_dir: str, tag: str, width: int, height: int,
                        size_px: int | None = None) -> str:
    """One concat-demuxer playlist of caption PNGs, so FFmpeg needs a single overlay input."""
    blank = os.path.join(work_dir, f"{tag}_blank.png")
    Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(blank)
    lines, t, files = [], 0.0, [blank]
    for n, (a, b, text) in enumerate(cues):
        a, b = max(a, t), min(b, total_len)
        if b - a < 0.02:
            continue
        if a - t > 0.001:
            lines += [f"file '{blank}'", f"duration {a - t:.3f}"]
        png = os.path.join(work_dir, f"{tag}_cap_{n}.png")
        render_caption(text, png, width, height, size_px=size_px)
        files.append(png)
        lines += [f"file '{png}'", f"duration {b - a:.3f}"]
        t = b
    lines += [f"file '{blank}'", f"duration {max(total_len - t, 0.04):.3f}", f"file '{blank}'"]
    playlist = os.path.join(work_dir, f"{tag}_captions.txt")
    with open(playlist, "w") as f:
        f.write("\n".join(lines))
    return playlist, files


# ---------- render ----------

def has_audio(path: str) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index",
                          "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30)
    return bool(out.stdout.strip())


def plan_source_timing(segments: list[dict], video_duration: float) -> list[Scene]:
    """Subtitles-only mode: the video keeps its own timing (no slow-down, no freeze). One scene per line; the caption
    is shown while the original speaker talks (end - start from the transcript)."""
    order = sorted(range(len(segments)), key=lambda i: segments[i]["start"])
    starts, kept = [], []
    for i in order:
        s = min(max(0.0, segments[i]["start"]), video_duration)
        if starts and s <= starts[-1] + MIN_SCENE:
            continue
        starts.append(s)
        kept.append(i)
    scenes: list[Scene] = []
    if not kept or starts[0] > MIN_SCENE:
        lead = starts[0] if kept else video_duration
        scenes.append(Scene(0.0, lead, out_len=lead))
    elif kept:
        starts[0] = 0.0
    for n, i in enumerate(kept):
        a = starts[n]
        b = starts[n + 1] if n + 1 < len(kept) else video_duration
        slot = max(b - a, MIN_SCENE)
        speech = (segments[i].get("end") or (a + slot * 0.9)) - segments[i]["start"]
        sc = Scene(a, b, audio_index=i, text=segments[i]["translated_text"], out_len=slot)
        sc.audio_len = min(max(speech, 0.8), max(slot - 0.05, 0.3))
        sc.action = "source"
        scenes.append(sc)
    t = 0.0
    for sc in scenes:
        sc.out_start = t
        t += sc.out_len
    return scenes


def probe_video(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=30).stdout
    info = json.loads(out)
    num, den = info["streams"][0]["r_frame_rate"].split("/")
    return {"width": int(info["streams"][0]["width"]), "height": int(info["streams"][0]["height"]),
            "fps": float(num) / float(den or 1), "duration": float(info["format"]["duration"])}


def _blur_region(rect, src: str, name: str) -> str:
    x, y, w, h = rect
    r = max(1, min(int(min(w, h) / 4) - 1, 30))  # chroma planes are half size
    return (f"[{src}]split=2[{name}_m][{name}_s];"
            f"[{name}_s]crop={w}:{h}:{x}:{y},boxblur={r}:2[{name}_b];"
            f"[{name}_m][{name}_b]overlay={x}:{y}[{name}_o]")


_LOGO_POS = {
    "top-right": "W-w-30:30", "top-left": "30:30",
    "bottom-right": "W-w-30:H-h-30", "bottom-left": "30:H-h-30", "center": "(W-w)/2:(H-h)/2",
}


def _render_single(video_path: str, segments: list[dict], scenes: list[Scene], fx: EffectOptions,
                   output_path: str, work_dir: str, tag: str, timeout: int = 1800,
                   src_offset: float = 0.0, threads: int | None = None) -> dict:
    work_dir = os.path.abspath(work_dir)
    info = probe_video(video_path)
    W, H, fps = info["width"], info["height"], min(max(info["fps"], 1), 60)
    speed = min(max(fx.speed, 0.5), 2.0)
    total_len = sum(s.out_len for s in scenes) / speed

    cmd = ["ffmpeg", "-y"] + (["-ss", f"{src_offset:.3f}"] if src_offset else []) + ["-i", video_path]
    audio_inputs: dict[int, int] = {}
    nxt = 1
    for sc in scenes:
        if sc.audio_index is not None and not fx.source_audio and segments[sc.audio_index].get("audio_path"):
            cmd += ["-i", segments[sc.audio_index]["audio_path"]]
            audio_inputs[sc.audio_index] = nxt
            nxt += 1
    logo_idx = None
    if fx.logo_path and os.path.exists(fx.logo_path):
        cmd += ["-i", fx.logo_path]
        logo_idx = nxt
        nxt += 1

    bg_idx = None
    if fx.background_path and os.path.exists(fx.background_path):
        cmd += (["-ss", f"{src_offset:.3f}"] if src_offset else []) + ["-i", fx.background_path]
        bg_idx = nxt
        nxt += 1

    cue_list = caption_cues(scenes, speed)
    cap_idx, cap_files = None, []
    if fx.captions and cue_list:
        cap_h = int(H * 0.22)
        playlist, cap_files = build_caption_track(cue_list, total_len, work_dir, tag, W, cap_h, fx.caption_px)
        cmd += ["-f", "concat", "-safe", "0", "-i", playlist]
        cap_idx = nxt
        nxt += 1

    f = []
    # 1. Retime every scene to its voice-over, then join.
    afmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=" + ("stereo" if fx.source_audio else "mono")
    labels = []
    for n, sc in enumerate(scenes):
        v = f"[0:v]trim=start={sc.src_start:.3f}:end={sc.src_end:.3f},setpts=(PTS-STARTPTS)/{sc.video_speed:.5f},fps={fps:.3f}"
        if sc.freeze > 0.001:
            v += f",tpad=stop_mode=clone:stop_duration={sc.freeze:.3f}"
        f.append(f"{v}[v{n}]")
        if fx.source_audio:   # subtitles only: the picture and its own sound stay in sync, untouched
            a = (f"[0:a]atrim=start={sc.src_start:.3f}:end={sc.src_end:.3f},asetpts=PTS-STARTPTS,aresample=44100,"
                 f"{afmt},apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f}")
        elif sc.audio_index is None or sc.audio_index not in audio_inputs:
            a = f"anullsrc=r=44100:cl=mono,atrim=end={sc.out_len:.3f}"
        else:
            a = f"[{audio_inputs[sc.audio_index]}:a]aresample=44100"
            if abs(sc.tempo - 1.0) > 0.001:
                a += f",atempo={sc.tempo:.4f}"
            a += f",{afmt},apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f}"
        f.append(f"{a},{afmt},asetpts=PTS-STARTPTS[a{n}]")
        labels.append(f"[v{n}][a{n}]")
        if bg_idx is not None:
            b = (f"[{bg_idx}:a]atrim=start={sc.src_start:.3f}:end={sc.src_end:.3f},asetpts=PTS-STARTPTS")
            if sc.video_speed < 0.999:
                b += f",atempo={sc.video_speed:.4f}"
            b += (f",aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                  f"apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f},asetpts=PTS-STARTPTS[b{n}]")
            f.append(b)
    f.append(f"{''.join(labels)}concat=n={len(scenes)}:v=1:a=1[vcat][acat]")
    acat = "acat"
    if bg_idx is not None:
        f.append(f"{''.join(f'[b{n}]' for n in range(len(scenes)))}concat=n={len(scenes)}:v=0:a=1[bgcat]")
        f.append("[acat]aformat=channel_layouts=stereo[vo]")
        f.append(f"[bgcat]volume={fx.background_volume:.3f}[bgq]")
        if fx.duck_background:   # the background dips whenever the voice speaks, then comes back
            f.append("[vo]asplit=2[vo1][vo2]")
            f.append("[bgq][vo1]sidechaincompress=threshold=0.02:ratio=12:attack=10:release=350[bgd]")
            f.append("[vo2][bgd]amix=inputs=2:normalize=0:duration=first[acat2]")
        else:
            f.append("[vo][bgq]amix=inputs=2:normalize=0:duration=first[acat2]")
        acat = "acat2"
    cur = "vcat"

    def chain(expr: str, name: str):
        nonlocal cur
        f.append(f"[{cur}]{expr}[{name}]")
        cur = name

    # 2. Effects, then captions last so they are never flipped, graded or sped up.
    if fx.blur_subtitles and fx.subtitle_rect:
        f.append(_blur_region(fx.subtitle_rect, cur, "bs"))
        cur = "bs_o"
    if fx.blur_watermark:
        for k, rect in enumerate(fx.watermark_rects):
            f.append(_blur_region(rect, cur, f"bw{k}"))
            cur = f"bw{k}_o"
        f.append(f"[{cur}]split=2[w_main][w_src];"
                 f"[w_src]crop=trunc(iw*0.25):trunc(ih*0.12):trunc(iw*0.75):trunc(ih*0.88),boxblur=20:10[w_blur];"
                 f"[w_main][w_blur]overlay=W-w:H-h[wm1]")
        cur = "wm1"
    if fx.flip_h:
        chain("hflip", "fh")
    if fx.flip_v:
        chain("vflip", "fv")
    if (fx.brightness, fx.contrast, fx.saturation) != (0.0, 1.0, 1.0):
        chain(f"eq=brightness={fx.brightness:.3f}:contrast={fx.contrast:.3f}:saturation={fx.saturation:.3f}", "gr")
    if speed != 1.0:
        chain(f"setpts=PTS/{speed:.4f}", "sp")
    if logo_idx is not None:
        pos = _LOGO_POS.get(fx.logo_position, _LOGO_POS["top-right"])
        f.append(f"[{logo_idx}:v]scale=trunc({W}*{fx.logo_width_frac:.3f}/2)*2:-2[lg]")
        f.append(f"[{cur}][lg]overlay={pos}[wl]")
        cur = "wl"
    if cap_idx is not None:
        f.append(f"[{cap_idx}:v]format=rgba[cp]")
        if fx.subtitle_rect:  # sit exactly where the blurred source subtitles were
            cy = min(fx.subtitle_rect[1] + fx.subtitle_rect[3] + int(H * 0.01), H)
            cap_y = f"{max(0, min(cy - cap_h, H - cap_h))}"
        else:
            cap_y = f"H-h-{int(H * 0.04)}"
        f.append(f"[{cur}][cp]overlay=0:{cap_y}:eof_action=pass:format=auto[wc]")
        cur = "wc"
    acur = acat
    if speed != 1.0:
        f.append(f"[{acat}]atempo={speed:.4f}[asp]")
        acur = "asp"

    script = os.path.join(work_dir, f"{tag}_filter.txt")
    with open(script, "w") as fh:
        fh.write(";\n".join(f))
    cmd += ["-/filter_complex", script, "-map", f"[{cur}]", "-map", f"[{acur}]",
            "-r", f"{fps:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if threads:
        cmd += ["-threads", str(threads)]
    cmd += ["-c:a", "aac", "-t", f"{total_len:.3f}", "-movflags", "+faststart", output_path]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    finally:
        for p in cap_files + [script, os.path.join(work_dir, f"{tag}_captions.txt")]:
            if os.path.exists(p):
                os.remove(p)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode(errors="replace")[-2000:])
    return {"duration": total_len, "cues": cue_list}


# ---------- parallel render ----------

PARALLEL_MIN_SECONDS = float(os.getenv("PARALLEL_RENDER_MIN_SECONDS", "60"))
CHUNK_TARGET_SECONDS = float(os.getenv("PARALLEL_RENDER_CHUNK_SECONDS", "40"))


def _split_scenes(scenes: list[Scene], parts: int) -> list[list[Scene]]:
    """Consecutive groups of scenes with roughly equal output length."""
    total = sum(sc.out_len for sc in scenes)
    groups, cur, acc = [], [], 0.0
    for sc in scenes:
        cur.append(sc)
        acc += sc.out_len
        if acc >= total / parts * (len(groups) + 1) and len(groups) < parts - 1:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def render(video_path: str, segments: list[dict], scenes: list[Scene], fx: EffectOptions,
           output_path: str, work_dir: str, tag: str, timeout: int = 1800) -> dict:
    """Render the dub. Long videos are cut into scene groups rendered on separate CPU cores, then joined."""
    speed = min(max(fx.speed, 0.5), 2.0)
    total_len = sum(s.out_len for s in scenes) / speed
    cores = os.cpu_count() or 2
    parts = min(cores, int(total_len // CHUNK_TARGET_SECONDS), len(scenes))
    if total_len < PARALLEL_MIN_SECONDS or parts < 2:
        return _render_single(video_path, segments, scenes, fx, output_path, work_dir, tag, timeout)

    work_dir = os.path.abspath(work_dir)
    groups = _split_scenes(scenes, parts)
    threads = max(2, cores // len(groups))
    chunk_paths = [os.path.join(work_dir, f"{tag}_c{k}.mp4") for k in range(len(groups))]

    def job(k: int):
        group = groups[k]
        offset, out0 = group[0].src_start, group[0].out_start
        local = [replace(sc, src_start=sc.src_start - offset, src_end=sc.src_end - offset,
                         out_start=sc.out_start - out0) for sc in group]
        return _render_single(video_path, segments, local, fx, chunk_paths[k], work_dir, f"{tag}_c{k}",
                              timeout, src_offset=offset, threads=threads)

    playlist = os.path.join(work_dir, f"{tag}_chunks.txt")
    try:
        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            list(pool.map(job, range(len(groups))))
        with open(playlist, "w") as fh:
            fh.write("\n".join(f"file '{p}'" for p in chunk_paths))
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", playlist, "-c:v", "copy", "-c:a", "aac",
             "-b:a", "160k", "-movflags", "+faststart", output_path],
            capture_output=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.decode(errors="replace")[-2000:])
    finally:
        for p in chunk_paths + [playlist]:
            if os.path.exists(p):
                os.remove(p)
    return {"duration": total_len, "cues": caption_cues(scenes, speed)}
