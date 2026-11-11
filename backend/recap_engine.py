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

from admin import settings as runtime_settings

BREATH = 0.10  # silence kept after each voice clip so clips never run together
MIN_SCENE = 0.05

# NotoSansMyanmar.ttc index of the Bold face; the other candidates are single-face files.
FONT_CANDIDATES = [
    (os.getenv("BURMESE_FONT_PATH", ""), 0),
    ("/System/Library/Fonts/NotoSansMyanmar.ttc", 1),
    ("/System/Library/Fonts/Supplemental/Myanmar Sangam MN.ttc", 0),
    (os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansMyanmar-Bold.ttf"), 0),   # shipped with the app (SIL OFL, see fonts/NOTICE.txt): a Linux server has no Burmese font and the captions came out as empty boxes
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
    logo_xy: tuple | None = None  # dragged position (left, top) as fractions of the frame; overrides logo_position
    extra_blur_rects: list = field(default_factory=list)  # user-drawn boxes, pixel rects IN THE OUTPUT FRAME, blurred the whole video
    out_size: tuple | None = None  # (width, height) of the final frame; None = same as the source
    fit_mode: str = "blur"         # blur: whole picture over a blurred copy | crop: fill the frame, pan_x/pan_y pick the part kept
    pan_x: float = 0.5
    pan_y: float = 0.5
    captions: bool = True
    subtitle_rect: tuple | None = None  # pixel (x, y, w, h) of detected source subtitles; None = nothing to blur
    watermark_rects: list = field(default_factory=list)  # detected static-text watermarks, pixel rects
    subtitle_windows: list | None = None  # [(start, end)] SOURCE seconds when the source subtitle is really on screen; None = blur the band all the time
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


def burmese_font_available() -> bool:
    return any(path and os.path.isfile(path) for path, _ in FONT_CANDIDATES)


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
    from common import display_size
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True, timeout=30).stdout
    info = json.loads(out)
    num, den = info["streams"][0]["r_frame_rate"].split("/")
    width, height = display_size(path)   # as shown (a rotated phone clip is portrait), the size the filters see
    return {"width": width, "height": height,
            "fps": float(num) / float(den or 1), "duration": float(info["format"]["duration"])}


def ffmpeg_error(stderr: bytes) -> str:
    """The useful part of ffmpeg's error output: its long version / build banner is dropped, the end (the real reason) is kept."""
    lines = [l for l in stderr.decode(errors="replace").splitlines()
             if l.strip() and not l.startswith(("ffmpeg version", "  built with", "  configuration:", "  lib"))]
    return ("ffmpeg: " + "\n".join(lines))[-1500:]


_FFMPEG_MAJOR: int | None = None


def ffmpeg_major() -> int:
    """Major version of the ffmpeg on this machine (cached); 99 when it cannot be read (a git build: assume new)."""
    global _FFMPEG_MAJOR
    if _FFMPEG_MAJOR is None:
        try:
            first = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10).stdout.splitlines()[0]
            m = re.search(r"version n?(\d+)\.", first)
            _FFMPEG_MAJOR = int(m.group(1)) if m else 99
        except Exception:
            _FFMPEG_MAJOR = 99
    return _FFMPEG_MAJOR


def filter_script_args(path: str) -> list:
    """Read the filter graph from a file. ffmpeg 7+ spells it `-/filter_complex file`; ffmpeg 6 (Ubuntu 24.04) only knows `-filter_complex_script file`."""
    return ["-/filter_complex", path] if ffmpeg_major() >= 7 else ["-filter_complex_script", path]


def _blur_region(rect, src: str, name: str, windows: list | None = None) -> str:
    """Blur `rect`; with `windows` [(a, b)] only while the stream time t is inside one of them."""
    x, y, w, h = rect
    r = max(1, min(int(min(w, h) / 4) - 1, 30))  # chroma planes are half size
    enable = ""
    if windows is not None:
        enable = ":enable='" + ("+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in windows) or "0") + "'"
    return (f"[{src}]split=2[{name}_m][{name}_s];"
            f"[{name}_s]crop={w}:{h}:{x}:{y},boxblur={r}:2[{name}_b];"
            f"[{name}_m][{name}_b]overlay={x}:{y}{enable}[{name}_o]")


_LOGO_POS = {
    "top-right": "W-w-30:30", "top-left": "30:30",
    "bottom-right": "W-w-30:H-h-30", "bottom-left": "30:H-h-30", "center": "(W-w)/2:(H-h)/2",
}


def build_voice_track(segments: list[dict], scenes: list[Scene], work_dir: str, tag: str) -> tuple[str, dict[int, tuple[float, float]]] | None:
    """Put every voice clip the scenes use into ONE wav (44.1 kHz mono, clips back to back) and return (path, {segment index: (start, length)}).
    Why: giving ffmpeg one `-i` per clip means ~1 demuxer + decoder per clip (186 inputs on a 10-minute film = hundreds of threads: it hit the
    service's task limit and the render died with "pthread_create() failed"). With one file the filter graph just trims it.
    Each clip is decoded to raw PCM by ffmpeg, so the length (and so the offset) is exact by construction. None = nothing to put in."""
    import wave
    used = []
    for sc in scenes:
        if sc.audio_index is not None and sc.audio_index not in used and segments[sc.audio_index].get("audio_path"):
            used.append(sc.audio_index)
    if not used:
        return None
    rate = 44100

    def decode(i: int) -> bytes:
        res = subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-i", segments[i]["audio_path"], "-f", "s16le", "-ar", str(rate), "-ac", "1", "-"],
                             capture_output=True, timeout=120)
        if res.returncode != 0:
            raise RuntimeError(ffmpeg_error(res.stderr))
        return res.stdout

    with ThreadPoolExecutor(max_workers=3) as pool:
        pcm = list(pool.map(decode, used))
    path = os.path.join(os.path.abspath(work_dir), f"{tag}_voice.wav")
    offsets, pos = {}, 0
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        for i, data in zip(used, pcm):
            n = len(data) // 2
            offsets[i] = (pos / rate, n / rate)
            w.writeframes(data[: n * 2])
            pos += n
    return path, offsets


def _render_single(video_path: str, segments: list[dict], scenes: list[Scene], fx: EffectOptions,
                   output_path: str, work_dir: str, tag: str, timeout: int = 1800,
                   src_offset: float = 0.0, threads: int | None = None, audio_only: bool = False,
                   voice_track: tuple | None = None) -> dict:
    """audio_only: build ONLY the final audio track (voice-over + background, retimed like the video) as AAC in `output_path` (.m4a).
    Used by the on-device render: the phone draws the picture, the server makes the sound with the same filter graph."""
    work_dir = os.path.abspath(work_dir)
    info = probe_video(video_path)
    SW, SH, fps = info["width"], info["height"], min(max(info["fps"], 1), 60)
    W, H = fx.out_size or (SW, SH)   # everything after the reframe step works in the output frame
    reframed = (W, H) != (SW, SH)
    speed = min(max(fx.speed, 0.5), 2.0)
    total_len = sum(s.out_len for s in scenes) / speed

    cmd = ["ffmpeg", "-y"] + (["-ss", f"{src_offset:.3f}"] if src_offset else []) + ["-i", video_path]
    audio_inputs: dict[int, tuple[int, float, float]] = {}   # segment index -> (input number, start, length) inside the voice track
    nxt = 1
    own_track = None
    if not fx.source_audio:
        track = voice_track if voice_track is not None else build_voice_track(segments, scenes, work_dir, tag)
        if voice_track is None and track:
            own_track = track[0]
        if track:
            cmd += ["-i", track[0]]
            for i, (start, length) in track[1].items():
                audio_inputs[i] = (nxt, start, length)
            nxt += 1
    logo_idx = None
    if fx.logo_path and os.path.exists(fx.logo_path) and not audio_only:
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
    if fx.captions and cue_list and not audio_only:
        cap_h = int(H * 0.22)
        cap_px = fx.caption_px
        if cap_px and reframed:   # the picture is scaled by this factor, so the caption keeps its size relative to it
            cap_px = max(12, int(cap_px * (max if fx.fit_mode == "crop" else min)(W / SW, H / SH)))
        playlist, cap_files = build_caption_track(cue_list, total_len, work_dir, tag, W, cap_h, cap_px)
        cmd += ["-f", "concat", "-safe", "0", "-i", playlist]
        cap_idx = nxt
        nxt += 1

    f = []
    # 1. Retime every scene to its voice-over, then join.
    afmt = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=" + ("stereo" if fx.source_audio else "mono")
    labels = []
    # Source subtitle blurred only while it is on screen: blur the SOURCE stream (source time) before it is cut into scenes.
    pre_blur = bool(fx.blur_subtitles and fx.subtitle_rect and fx.subtitle_windows is not None) and not audio_only
    if pre_blur:
        local = [(max(a - src_offset, 0.0), b - src_offset) for a, b in fx.subtitle_windows if b - src_offset > 0]
        f.append(_blur_region(fx.subtitle_rect, "0:v", "bs", local))
        f.append(f"[bs_o]split={len(scenes)}" + "".join(f"[sv{n}]" for n in range(len(scenes))) if len(scenes) > 1
                 else "[bs_o]null[sv0]")
    for n, sc in enumerate(scenes):
        v = f"[{'sv' + str(n) if pre_blur else '0:v'}]trim=start={sc.src_start:.3f}:end={sc.src_end:.3f},setpts=(PTS-STARTPTS)/{sc.video_speed:.5f},fps={fps:.3f}"
        if sc.freeze > 0.001:
            v += f",tpad=stop_mode=clone:stop_duration={sc.freeze:.3f}"
        if not audio_only:
            f.append(f"{v}[v{n}]")
        if fx.source_audio:   # subtitles only: the picture and its own sound stay in sync, untouched
            a = (f"[0:a]atrim=start={sc.src_start:.3f}:end={sc.src_end:.3f},asetpts=PTS-STARTPTS,aresample=44100,"
                 f"{afmt},apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f}")
        elif sc.audio_index is None or sc.audio_index not in audio_inputs:
            a = f"anullsrc=r=44100:cl=mono,atrim=end={sc.out_len:.3f}"
        else:
            vi, vstart, vlen = audio_inputs[sc.audio_index]
            a = f"[{vi}:a]atrim=start={vstart:.6f}:end={vstart + vlen:.6f},asetpts=PTS-STARTPTS,aresample=44100"
            if abs(sc.tempo - 1.0) > 0.001:
                a += f",atempo={sc.tempo:.4f}"
            a += f",{afmt},apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f}"
        f.append(f"{a},{afmt},asetpts=PTS-STARTPTS[a{n}]")
        labels.append(f"[a{n}]" if audio_only else f"[v{n}][a{n}]")
        if bg_idx is not None:
            b = (f"[{bg_idx}:a]atrim=start={sc.src_start:.3f}:end={sc.src_end:.3f},asetpts=PTS-STARTPTS")
            if sc.video_speed < 0.999:
                b += f",atempo={sc.video_speed:.4f}"
            b += (f",aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                  f"apad=whole_dur={sc.out_len:.3f},atrim=end={sc.out_len:.3f},asetpts=PTS-STARTPTS[b{n}]")
            f.append(b)
    if audio_only:
        f.append(f"{''.join(labels)}concat=n={len(scenes)}:v=0:a=1[acat]")
    else:
        f.append(f"{''.join(labels)}concat=n={len(scenes)}:v=1:a=1[vcat][acat]")
    acat = "acat"
    if bg_idx is not None:
        f.append(f"{''.join(f'[b{n}]' for n in range(len(scenes)))}concat=n={len(scenes)}:v=0:a=1[bgcat]")
        f.append("[acat]aformat=channel_layouts=stereo[vo]")
        f.append(f"[bgcat]volume={fx.background_volume:.3f}[bgq]")
        if fx.duck_background:   # the background dips whenever the voice speaks, then comes back
            f.append("[vo]asplit=2[vo1][vo2]")
            f.append("[bgq][vo1]sidechaincompress=threshold=0.03:ratio=4:attack=20:release=400[bgd]")
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
    if audio_only:   # no picture: write the sound only, same graph as the full render
        acur = acat
        if speed != 1.0:
            f.append(f"[{acat}]atempo={speed:.4f}[asp]")
            acur = "asp"
        script = os.path.join(work_dir, f"{tag}_filter.txt")
        with open(script, "w") as fh:
            fh.write(";\n".join(f))
        try:
            res = subprocess.run(cmd + [*filter_script_args(script), "-map", f"[{acur}]", "-vn", "-c:a", "aac", "-b:a", "128k",
                                        "-t", f"{total_len:.3f}", output_path], capture_output=True, timeout=timeout)
        finally:
            if os.path.exists(script):
                os.remove(script)
        if res.returncode != 0:
            raise RuntimeError(ffmpeg_error(res.stderr))
        return {"duration": total_len, "cues": cue_list}
    if fx.blur_subtitles and fx.subtitle_rect and not pre_blur:
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
    if reframed:
        if abs(W * SH - H * SW) <= 2 * max(SW, SH):   # same shape, only smaller (a 4K upload in "Original" format): plain scale, no bars, no blurred copy
            chain(f"scale={W}:{H}:flags=bicubic,setsar=1", "rf")
        elif fx.fit_mode == "crop":
            px, py = min(max(fx.pan_x, 0.0), 1.0), min(max(fx.pan_y, 0.0), 1.0)
            chain(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:x='(iw-{W})*{px:.4f}':y='(ih-{H})*{py:.4f}',setsar=1", "rf")
        else:
            sw, sh = max(16, int(W / 8) // 2 * 2), max(16, int(H / 8) // 2 * 2)   # blur a small copy, then scale up: same look, ~5x faster than blurring full size
            f.append(f"[{cur}]split=2[rf_a][rf_b];"
                     f"[rf_a]scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},boxblur=3:2,scale={W}:{H}:flags=bilinear[rf_bg];"
                     f"[rf_b]scale={W}:{H}:force_original_aspect_ratio=decrease[rf_fg];"
                     f"[rf_bg][rf_fg]overlay=(W-w)/2:(H-h)/2,setsar=1[rf]")
            cur = "rf"
    if fx.flip_h:
        chain("hflip", "fh")
    if fx.flip_v:
        chain("vflip", "fv")
    for k, rect in enumerate(fx.extra_blur_rects):   # drawn on the preview of the final frame, so after reframe + flip
        f.append(_blur_region(rect, cur, f"bm{k}"))
        cur = f"bm{k}_o"
    if (fx.brightness, fx.contrast, fx.saturation) != (0.0, 1.0, 1.0):
        chain(f"eq=brightness={fx.brightness:.3f}:contrast={fx.contrast:.3f}:saturation={fx.saturation:.3f}", "gr")
    if speed != 1.0:
        chain(f"setpts=PTS/{speed:.4f}", "sp")
    if logo_idx is not None:
        pos = _LOGO_POS.get(fx.logo_position, _LOGO_POS["top-right"])
        if fx.logo_xy:
            pos = f"{fx.logo_xy[0] * W:.0f}:{fx.logo_xy[1] * H:.0f}"
        f.append(f"[{logo_idx}:v]scale=trunc({W}*{fx.logo_width_frac:.3f}/2)*2:-2[lg]")
        f.append(f"[{cur}][lg]overlay={pos}[wl]")
        cur = "wl"
    if cap_idx is not None:
        f.append(f"[{cap_idx}:v]format=rgba[cp]")
        if fx.subtitle_rect and not reframed:  # sit exactly where the blurred source subtitles were
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
    cmd += [*filter_script_args(script), "-map", f"[{cur}]", "-map", f"[{acur}]",
            "-r", f"{fps:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(runtime_settings.video_crf()), "-pix_fmt", "yuv420p"]
    if threads:
        cmd += ["-threads", str(threads)]
    cmd += ["-c:a", "aac", "-t", f"{total_len:.3f}", "-movflags", "+faststart", output_path]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=timeout)
    finally:
        for p in cap_files + [script, os.path.join(work_dir, f"{tag}_captions.txt")] + ([own_track] if own_track else []):
            if os.path.exists(p):
                os.remove(p)
    if res.returncode != 0:
        raise RuntimeError(ffmpeg_error(res.stderr))
    return {"duration": total_len, "cues": cue_list}


# ---------- on-device render plan ----------

def device_plan(info: dict, scenes: list[Scene], fx: EffectOptions, cues: list, total_len: float) -> dict:
    """Everything a PHONE needs to draw the picture itself (the server only makes the sound): timeline, effects, caption look.
    Positions of source things are fractions of the DISPLAYED source picture; manual blur boxes are pixels of the output frame."""
    SW, SH = info["width"], info["height"]
    W, H = fx.out_size or (SW, SH)
    reframed = (W, H) != (SW, SH)
    speed = min(max(fx.speed, 0.5), 2.0)
    norm = lambda r: [r[0] / SW, r[1] / SH, r[2] / SW, r[3] / SH]
    blur_rects = []
    if fx.blur_watermark:
        blur_rects = [norm(r) for r in fx.watermark_rects] + [[0.75, 0.88, 0.25, 0.12]]
    cap_h = int(H * 0.22)
    cap_px = fx.caption_px
    if cap_px and reframed:
        cap_px = max(12, int(cap_px * (max if fx.fit_mode == "crop" else min)(W / SW, H / SH)))
    size = max(int(W * 0.05), 18)
    if cap_px:
        size = int(min(max(cap_px, W * 0.035), W * 0.075))
    if fx.subtitle_rect and not reframed:
        cy = min(fx.subtitle_rect[1] + fx.subtitle_rect[3] + int(H * 0.01), H)
        cap_y = max(0, min(cy - cap_h, H - cap_h))
    else:
        cap_y = H - cap_h - int(H * 0.04)
    return {
        "version": 1, "duration": total_len, "fps": min(max(info["fps"], 1), 30),
        "out": [W, H], "source": [SW, SH], "fit_mode": fx.fit_mode, "pan": [fx.pan_x, fx.pan_y],
        "flip_h": bool(fx.flip_h), "speed": speed,
        "grade": {"brightness": fx.brightness, "contrast": fx.contrast, "saturation": fx.saturation},
        "scenes": [[sc.src_start, sc.src_end, sc.video_speed, sc.out_start, sc.out_len] for sc in scenes],
        "blur_rects": blur_rects,
        "subtitle": ({"rect": norm(fx.subtitle_rect),
                      "windows": [list(w) for w in fx.subtitle_windows] if fx.subtitle_windows is not None else None}
                     if fx.blur_subtitles and fx.subtitle_rect else None),
        "manual_blurs": [list(r) for r in fx.extra_blur_rects],
        "caption": {"size": size, "bottom": cap_y + cap_h - 8, "max_w": int(W * 0.88)},
        "cues": [[round(a, 3), round(b, 3), t] for a, b, t in cues],
        "logo": ({"pos": fx.logo_position, "xy": list(fx.logo_xy) if fx.logo_xy else None, "width": fx.logo_width_frac}
                 if fx.logo_path else None),
    }


# ---------- parallel render ----------

# A long film is rendered as several SHORT SEGMENTS (a few dozen scenes each), one after another, then joined.
# Why: one ffmpeg for the whole film keeps growing in memory (~200 MB per minute on the 1-CPU server, 1.3 GB+ at 5 of 10 minutes, then it
# stalled at the service's memory limit). A segment only holds its own scenes, so peak memory no longer depends on the film's length.
SEGMENT_MIN_SECONDS = float(os.getenv("RENDER_SEGMENT_MIN_SECONDS", "60"))   # shorter results are rendered in one piece
SEGMENT_SECONDS = float(os.getenv("RENDER_SEGMENT_SECONDS", "60"))           # target output length of one segment
SEGMENT_MAX_SCENES = int(os.getenv("RENDER_SEGMENT_MAX_SCENES", "40"))       # ...and at most this many scenes
RENDER_WORKERS = int(os.getenv("RENDER_WORKERS", "1"))                       # segments rendered at the same time (raise only on a big server)


def _split_scenes(scenes: list[Scene], max_seconds: float, max_scenes: int) -> list[list[Scene]]:
    """Consecutive groups of scenes: each at most `max_scenes` scenes and about `max_seconds` of output."""
    groups, cur, acc = [], [], 0.0
    for sc in scenes:
        if cur and (len(cur) >= max_scenes or acc + sc.out_len > max_seconds):
            groups.append(cur)
            cur, acc = [], 0.0
        cur.append(sc)
        acc += sc.out_len
    if cur:
        groups.append(cur)
    return groups


def render(video_path: str, segments: list[dict], scenes: list[Scene], fx: EffectOptions,
           output_path: str, work_dir: str, tag: str, timeout: int = 1800) -> dict:
    """Render the dub. A long result is cut into short scene groups (segments), each rendered by its own ffmpeg, then joined."""
    speed = min(max(fx.speed, 0.5), 2.0)
    total_len = sum(s.out_len for s in scenes) / speed
    groups = _split_scenes(scenes, SEGMENT_SECONDS * speed, SEGMENT_MAX_SCENES)
    if total_len < SEGMENT_MIN_SECONDS or len(groups) < 2:
        return _render_single(video_path, segments, scenes, fx, output_path, work_dir, tag, timeout)

    work_dir = os.path.abspath(work_dir)
    workers = max(1, min(RENDER_WORKERS, len(groups)))
    threads = max(2, (os.cpu_count() or 2) // workers)
    chunk_paths = [os.path.join(work_dir, f"{tag}_c{k}.mp4") for k in range(len(groups))]
    track = None if fx.source_audio else build_voice_track(segments, scenes, work_dir, tag)   # ONE voice file shared by all segments

    def job(k: int):
        group = groups[k]
        offset, out0 = group[0].src_start, group[0].out_start
        local = [replace(sc, src_start=sc.src_start - offset, src_end=sc.src_end - offset,
                         out_start=sc.out_start - out0) for sc in group]
        return _render_single(video_path, segments, local, fx, chunk_paths[k], work_dir, f"{tag}_c{k}",
                              timeout, src_offset=offset, threads=threads, voice_track=track or ())

    playlist = os.path.join(work_dir, f"{tag}_chunks.txt")
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(job, range(len(groups))))
        with open(playlist, "w") as fh:
            fh.write("\n".join(f"file '{p}'" for p in chunk_paths))
        res = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", playlist, "-c:v", "copy", "-c:a", "aac",
             "-b:a", "160k", "-movflags", "+faststart", output_path],
            capture_output=True, timeout=timeout)
        if res.returncode != 0:
            raise RuntimeError(ffmpeg_error(res.stderr))
    finally:
        for p in chunk_paths + [playlist] + ([track[0]] if track else []):
            if os.path.exists(p):
                os.remove(p)
    return {"duration": total_len, "cues": caption_cues(scenes, speed)}
