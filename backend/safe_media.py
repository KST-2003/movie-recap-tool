"""Safe handling of files uploaded by users (video, logo) before ffmpeg / OpenCV / Pillow work on them.

Why: ffmpeg decides the file format from the CONTENT, not the extension. A text file that is really an HLS playlist, a concat list
or an SDP can make ffmpeg/ffprobe open other URLs (SSRF: the server fetches addresses chosen by the uploader) or other local files,
and the API process holds every secret in its environment. Defence in depth:
 1. `inspect_video` (run at upload): ffprobe with the protocol whitelist, then only real video containers are accepted.
 2. `SAFE_IN` (`-protocol_whitelist file,pipe`) is put in front of every ffmpeg / ffprobe input that is the user's video or logo, so even a
    file that slipped through can only read itself (also set for OpenCV's own ffmpeg through OPENCV_FFMPEG_CAPTURE_OPTIONS).
 3. `clean_logo` decodes the logo with Pillow and saves a fresh PNG: the original bytes never reach ffmpeg.
Keep this module free of heavy imports (it is imported by the API and by every worker)."""
import json
import math
import os
import subprocess

# ffmpeg input options that forbid network and other protocols. Use as: ["ffmpeg", *SAFE_IN, "-i", user_file, ...]
SAFE_IN = ["-protocol_whitelist", "file,pipe"]

# OpenCV bundles its own ffmpeg; this makes cv2.VideoCapture obey the same rule (read when a capture is opened).
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "protocol_whitelist;file,pipe")

# ffprobe "format_name" tokens of real video files (mp4/mov/3gp = "mov,mp4,m4a,3gp,3g2,mj2", mkv/webm = "matroska,webm").
# NOT allowed on purpose: hls, applehttp, concat, ffconcat, sdp, rtsp, dash, image2, lavfi, data, and every *_pipe image format.
ALLOWED_FORMATS = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "avi", "flv", "mpegts", "mpeg", "asf", "ogg"}
MAX_DIMENSION = int(os.getenv("MAX_VIDEO_DIMENSION", "8192"))   # width and height, pixels (8K)
MAX_STREAMS = int(os.getenv("MAX_VIDEO_STREAMS", "32"))
LOGO_FORMATS = {"PNG", "JPEG", "WEBP", "GIF", "BMP"}
LOGO_MAX_PIXELS = 25_000_000      # refuse decompression bombs before decoding
LOGO_MAX_SIDE = 1024              # logos are small overlays: the saved PNG is shrunk to this


class UnsafeMedia(ValueError):
    """The uploaded file is not an accepted video / image (the message is safe to show to the user)."""


def inspect_video(path: str) -> dict:
    """Probe an uploaded video with the protocol whitelist and check it is a real video container.
    -> {"duration", "width", "height", "format"}; raises UnsafeMedia otherwise."""
    try:
        out = subprocess.run(
            ["ffprobe", *SAFE_IN, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=30, check=True).stdout
        info = json.loads(out)
    except Exception:
        raise UnsafeMedia("That file doesn't look like a valid video.")
    fmt = info.get("format") or {}
    names = {n for n in str(fmt.get("format_name", "")).split(",") if n}
    if not names or not names <= ALLOWED_FORMATS:
        raise UnsafeMedia("That file type is not supported. Use MP4, MOV, MKV, WebM, AVI, FLV or TS.")
    streams = info.get("streams") or []
    if len(streams) > MAX_STREAMS:
        raise UnsafeMedia("That video has too many tracks.")
    video = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        raise UnsafeMedia("That file has no video track.")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if not (2 <= width <= MAX_DIMENSION and 2 <= height <= MAX_DIMENSION):
        raise UnsafeMedia(f"Video size must be at most {MAX_DIMENSION} pixels per side.")
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        raise UnsafeMedia("That file doesn't look like a valid video.")
    if not math.isfinite(duration) or duration <= 0:
        raise UnsafeMedia("That file doesn't look like a valid video.")
    return {"duration": duration, "width": width, "height": height, "format": ",".join(sorted(names))}


def clean_logo(path: str) -> str:
    """Decode an uploaded logo with Pillow and save a fresh PNG next to it (returns the new path, deletes the original).
    Only real PNG / JPEG / WebP / GIF / BMP images pass; the original bytes never reach ffmpeg."""
    from PIL import Image
    new = os.path.splitext(path)[0] + "_clean.png"
    try:
        with Image.open(path) as im:
            if im.format not in LOGO_FORMATS:
                raise UnsafeMedia("The logo must be a PNG, JPEG, WebP, GIF or BMP image.")
            if im.width * im.height > LOGO_MAX_PIXELS:
                raise UnsafeMedia("That logo image is too large.")
            im.seek(0)
            frame = im.convert("RGBA")
        frame.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE))
        frame.save(new, "PNG")
    except UnsafeMedia:
        _remove(path)
        raise
    except Exception:
        _remove(path)
        raise UnsafeMedia("The logo must be a PNG, JPEG, WebP, GIF or BMP image.")
    _remove(path)
    return new


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
