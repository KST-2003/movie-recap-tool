"""Offline test: uploaded videos / logos cannot make ffmpeg fetch other URLs or read other files (security fix: ffmpeg hardening).
Everything happens on this machine; the only server is a throw-away listener on 127.0.0.1 that counts requests.
Run: python test_media_safety.py"""
import os
import re
import struct
import subprocess
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out",
                  TTS_PROVIDER="fake", GEMINI_API_KEY="x", DATABASE_URL=f"sqlite:///{tmp}/t.db", GLOBAL_DAILY_MINUTES="0",
                  GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="")

import safe_media  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


# ---- a throw-away server on loopback that records who calls it (stands in for an internal service the uploader wants to reach) ----
hits = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]


def write(name, data):
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())
    return path


def ffmpeg(out, *args):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=64x64:d=1:r=10", *args, out],
                       capture_output=True, text=True)
    return r.returncode == 0


def rejected(path):
    try:
        safe_media.inspect_video(path)
        return False
    except safe_media.UnsafeMedia:
        return True


# ---- 0. the hole: an HLS playlist named .mp4 makes the OLD probe command call an address chosen by the uploader ----
hls = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1:{PORT}/internal-secret/seg.ts\n#EXT-X-ENDLIST\n"
evil_hls = write("evil_hls.mp4", hls)
try:
    subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", evil_hls],
                   capture_output=True, timeout=30)   # exactly what common.media_duration used to run
except Exception:
    pass
before = len(hits)
print(("NOTE " if before else "NOTE not reproduced with this ffmpeg build: ") + f"old probe command made {before} request(s) to the local listener", flush=True)

# ---- 1. real videos pass ----
formats = {"mp4": ("a.mp4", ["-c:v", "mpeg4"]), "mkv": ("a.mkv", ["-c:v", "mpeg4"]), "avi": ("a.avi", ["-c:v", "mpeg4"]),
           "ts": ("a.ts", ["-c:v", "mpeg2video"]), "webm": ("a.webm", ["-c:v", "libvpx", "-b:v", "200k"]), "mov": ("a.mov", ["-c:v", "mpeg4"])}
accepted = 0
for label, (name, codec) in formats.items():
    path = os.path.join(tmp, name)
    if not ffmpeg(path, *codec):
        print(f"SKIP {label}: this ffmpeg build cannot make the test file", flush=True)
        continue
    info = safe_media.inspect_video(path)
    ok(abs(info["duration"] - 1.0) < 0.5 and info["width"] == 64, f"{label}: accepted ({info['format']}, {info['duration']:.1f}s)")
    accepted += 1
ok(accepted >= 3, "at least three real container formats were tested")

# ---- 2. hostile or wrong files are refused ----
ok(rejected(evil_hls), "HLS playlist disguised as .mp4: refused")
ok(len(hits) == before, f"... and inspecting it contacted nothing ({len(hits) - before} new requests)")
ok(rejected(write("evil_file.mp4", "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n")), "HLS pointing at a local file: refused")
ok(rejected(write("evil_concat.mkv", "ffconcat version 1.0\nfile '/etc/passwd'\n")), "concat list: refused")
ok(rejected(write("evil_sdp.mp4", f"v=0\no=- 0 0 IN IP4 127.0.0.1\ns=x\nc=IN IP4 127.0.0.1\nt=0 0\nm=video {PORT} RTP/AVP 96\na=rtpmap:96 H264/90000\n")), "SDP file: refused")
ok(rejected(write("empty.mp4", b"")), "empty file: refused")
ok(rejected(write("text.mp4", "hello, I am not a video\n" * 50)), "plain text: refused")
ok(rejected(write("random.mp4", os.urandom(4096))), "random bytes: refused")
png = os.path.join(tmp, "pic.png")
ffmpeg(png, "-frames:v", "1")
ok(rejected(png), "a PNG image uploaded as a video: refused")
wav = os.path.join(tmp, "a.wav")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1", wav], check=True)
ok(rejected(wav), "audio only (WAV): refused")
big = os.path.join(tmp, "wide.mkv")
if ffmpeg(big, "-vf", "scale=9000:16", "-c:v", "mpeg4"):
    ok(rejected(big), "9000 pixels wide: refused (size cap)")
ok(len(hits) == before, "nothing above contacted the local listener")

# ---- 3. logos: re-encoded to a clean PNG ----
def tiny_png(w, h):
    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * w for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


good = write("logo.png", tiny_png(40, 20))
new = safe_media.clean_logo(good)
ok(new.endswith("_clean.png") and os.path.exists(new) and not os.path.exists(good), "a real logo becomes a fresh PNG, the original is deleted")
from PIL import Image  # noqa: E402
ok(Image.open(new).size == (40, 20), "logo size kept")
for name, data in (("logo_hls.png", hls), ("logo_text.png", "not an image"), ("logo_empty.png", b"")):
    p = write(name, data)
    try:
        safe_media.clean_logo(p)
        ok(False, f"{name} should be refused")
    except safe_media.UnsafeMedia:
        ok(not os.path.exists(p), f"{name}: refused and deleted")
bomb = write("bomb.png", tiny_png(6000, 6000))   # 36 megapixels in a tiny file
try:
    safe_media.clean_logo(bomb)
    ok(False, "pixel bomb should be refused")
except safe_media.UnsafeMedia:
    ok(True, "36-megapixel logo: refused before decoding")

# ---- 4. every ffmpeg / ffprobe call on a user file carries the protocol whitelist ----
ok(safe_media.SAFE_IN == ["-protocol_whitelist", "file,pipe"], "SAFE_IN is the whitelist")
ok(os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS") == "protocol_whitelist;file,pipe", "OpenCV's ffmpeg gets the same whitelist")
missing = []
for fname in sorted(os.listdir(".")):
    if not fname.endswith(".py") or fname.startswith(("test_", "bench_", "generate_", "compare_")) or fname == "safe_media.py":
        continue
    for n, line in enumerate(open(fname, encoding="utf-8"), 1):
        user_input = re.search(r'"-i", (video_path|fx\.logo_path)\b', line)
        if ('"ffprobe"' in line or user_input) and "SAFE_IN" not in line:
            missing.append(f"{fname}:{n}: {line.strip()[:100]}")
ok(not missing, "all ffprobe calls and all ffmpeg inputs of the user's video / logo use SAFE_IN" + ("" if not missing else "\n   " + "\n   ".join(missing)))

# ---- 5. through the API ----
from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import main  # noqa: E402
from api import jobs as api_jobs  # noqa: E402
from db import Job, Session, User  # noqa: E402

api_jobs.jobs_queue.enqueue = lambda job_id: None
api_jobs.MAX_ACTIVE_JOBS_PER_USER = 1000   # this test is about file safety, not the active-job limit
with Session() as s:
    u = User(email="u@x.com", password_hash=auth.hash_password("password1"), daily_minutes=1000, monthly_minutes=100000)
    s.add(u)
    s.commit()
    headers = {"Authorization": "Bearer " + auth.make_token(u)}
client = TestClient(main.app)


def upload(video_path, logo=None):
    files = {"video_file": (os.path.basename(video_path), open(video_path, "rb"), "video/mp4")}
    if logo:
        files["custom_logo"] = (os.path.basename(logo), open(logo, "rb"), "image/png")
    return client.post("/api/jobs", headers=headers, files=files, data={"output": "subtitles"})


def job_count():
    with Session() as s:
        return s.query(Job).count()


r = upload(os.path.join(tmp, "a.mp4"))
ok(r.status_code == 200, f"API: a real video is accepted ({r.status_code})")
n = job_count()
r = upload(evil_hls)
ok(r.status_code == 400 and job_count() == n and len(hits) == before, f"API: the disguised playlist is refused ({r.status_code}), no job, no outbound request")
logo_src = write("logo2.png", tiny_png(30, 30))
r = upload(os.path.join(tmp, "a.mp4"), logo_src)
with Session() as s:
    job = s.get(Job, r.json()["job_id"])
    ok(r.status_code == 200 and job.logo_key.endswith("_clean.png"), f"API: a real logo is stored as a clean PNG ({job.logo_key[-20:]})")
n = job_count()
r = upload(os.path.join(tmp, "a.mp4"), write("logo_evil.png", hls))
ok(r.status_code == 400 and job_count() == n, f"API: a playlist uploaded as the logo is refused ({r.status_code}), no job")
left = [f for f in os.listdir(os.environ["UPLOAD_DIR"]) if os.path.isfile(os.path.join(os.environ["UPLOAD_DIR"], f))] + \
       [f for f in os.listdir(os.path.join(os.environ["UPLOAD_DIR"], "logos"))]
with Session() as s:
    kept = {os.path.basename(j.input_key) for j in s.query(Job).all()} | {os.path.basename(j.logo_key) for j in s.query(Job).all() if j.logo_key}
ok(set(left) <= kept, f"refused uploads leave no files behind ({len(left)} files, all belong to jobs)")

print("ALL OK")
