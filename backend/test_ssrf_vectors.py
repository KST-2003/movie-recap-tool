"""Offline test: can an uploaded file make ffmpeg / ffprobe fetch an address chosen by the uploader (SSRF)? Many file types, both for the
UNPROTECTED command lines (what the app used to run: reported as NOTES, it depends on the ffmpeg build) and for the protected ones (what it runs now:
must make ZERO requests). The only server involved is a throw-away listener on 127.0.0.1 that counts requests.
Run it on every ffmpeg you deploy (also inside the Docker image):  python test_ssrf_vectors.py"""
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

tmp = tempfile.mkdtemp()
os.environ.update(PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", GEMINI_API_KEY="x",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")

import safe_media  # noqa: E402
import sandbox  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


hits = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    do_HEAD = do_POST = do_GET

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_address[1]}"


def write(name, text):
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(text)
    return path


version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
print(f"NOTE ffmpeg under test: {version}", flush=True)

# CONTROL: the test must be able to see a fetch. ffprobe given an http address directly (no whitelist) must reach the listener.
_before = len(hits)
subprocess.run(["ffprobe", "-v", "error", f"{URL}/control.mp4"], capture_output=True, timeout=25)
ok(len(hits) > _before, f"control: ffprobe given an http:// address contacts the listener ({len(hits) - _before} request), so a fetch WOULD be seen below")

VECTORS = {
    "hls media playlist (http segment)": ("a.mp4", f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n{URL}/seg.ts\n#EXT-X-ENDLIST\n"),
    "hls with an http AES key": ("b.mp4", f'#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXT-X-KEY:METHOD=AES-128,URI="{URL}/key.bin"\n#EXTINF:10,\nseg.ts\n#EXT-X-ENDLIST\n'),
    "hls with an http init segment (EXT-X-MAP)": ("c.mp4", f'#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXT-X-MAP:URI="{URL}/init.mp4"\n#EXTINF:10,\nseg.m4s\n#EXT-X-ENDLIST\n'),
    "hls master playlist -> http variant": ("d.mp4", f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000\n{URL}/variant.m3u8\n"),
    "hls with an http audio rendition": ("e.mp4", f'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",NAME="x",URI="{URL}/audio.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=1000,AUDIO="a"\nv.m3u8\n'),
    "dash manifest with an http BaseURL": ("f.mp4", f'<?xml version="1.0"?><MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT10S"><BaseURL>{URL}/</BaseURL>'
                                                    '<Period><AdaptationSet mimeType="video/mp4"><Representation id="1" bandwidth="1000"><SegmentTemplate media="s.m4s" duration="2"/></Representation></AdaptationSet></Period></MPD>'),
    "ffconcat list with an http file": ("g.mp4", f"ffconcat version 1.0\nfile '{URL}/x.mp4'\n"),
    "concat (unsafe) with an http file": ("h.txt", f"file '{URL}/x.mp4'\n"),
    "hls named .m3u8": ("i.m3u8", f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\n{URL}/seg2.ts\n#EXT-X-ENDLIST\n"),
    "hls, segment on a second host name": ("j.mp4", f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://localhost:{server.server_address[1]}/seg3.ts\n#EXT-X-ENDLIST\n"),
}
files = {name: write(fname, text) for name, (fname, text) in VECTORS.items()}


def run_plain(cmd):
    try:
        subprocess.run(cmd, capture_output=True, timeout=25)
    except Exception:
        pass


# ---- 1. what the OLD command lines did (informational: depends on the ffmpeg build) ----
exposed = []
for name, path in files.items():
    before = len(hits)
    run_plain(["ffprobe", "-v", "error", "-show_entries", "format=duration", path])                       # the old upload probe
    run_plain(["ffmpeg", "-v", "error", "-t", "1", "-i", path, "-f", "null", "-"])                        # the old render input
    got = len(hits) - before
    if got:
        exposed.append(name)
    print(f"NOTE unprotected commands, {name}: {got} request(s) to the listener", flush=True)
print(f"NOTE {len(exposed)} of {len(files)} vectors reached the listener with the UNPROTECTED commands on this ffmpeg", flush=True)

# ---- 2. the upload gate refuses every one of them, and does not touch the network ----
base = len(hits)
refused = 0
for name, path in files.items():
    try:
        safe_media.inspect_video(path)
    except safe_media.UnsafeMedia:
        refused += 1
ok(refused == len(files), f"the upload gate refuses all {len(files)} disguised files")
ok(len(hits) == base, f"... and made {len(hits) - base} requests while doing it")

# ---- 3. even if a file got past the gate, the protected command lines cannot reach the network ----
base = len(hits)
for name, path in files.items():
    sandbox.run(["ffprobe", *safe_media.SAFE_IN, "-v", "error", "-show_entries", "format=duration", path], capture_output=True, timeout=25)
    sandbox.run(["ffmpeg", *safe_media.SAFE_IN, "-v", "error", "-t", "1", "-i", path, "-f", "null", "-"], capture_output=True, timeout=25)
ok(len(hits) == base, f"protected ffprobe / ffmpeg (protocol whitelist) on every vector: {len(hits) - base} requests")

# ---- 4. the whitelist really is what stops it (not luck): http is refused by name ----
r = sandbox.run(["ffprobe", "-protocol_whitelist", "file,pipe", "-v", "error", f"{URL}/direct.mp4"], capture_output=True, text=True, timeout=25)
ok("not on whitelist" in (r.stderr or "").lower() or r.returncode != 0, "a direct http:// input is refused by the whitelist itself")
ok(len(hits) == base, "... without a request")
print("ALL OK")
