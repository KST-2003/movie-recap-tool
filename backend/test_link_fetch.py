"""Offline: video from a RedNote share link. RedNote is replaced by a fake httpx transport (share link -> redirect -> page -> CDN file).
Checks: link picked out of the share sentence, only RedNote hosts contacted, page parsing (H.264 preferred), size cap, the API
(fetch, file for the owner only, a video made from link_id without uploading, rate limit). Run: python test_link_fetch.py"""
import json, os, subprocess, tempfile, time
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db",
                  TTS_PROVIDER="fake", DUB_PROVIDER="gemini", ALLOW_SIGNUP="true", LINK_FETCHES_PER_MINUTE="4")
import httpx
import link_fetch as lf
from fastapi.testclient import TestClient
import gemini_dub, pipeline
from main import app

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

video = f"{tmp}/v.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=25:d=6", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
DATA = open(video, "rb").read()
state = {"note": {"video": {"media": {"stream": {
    "h265": [{"masterUrl": "http://sns-v1.rednotecdn.com/stream/a_265.mp4", "videoCodec": "hevc", "height": 1920, "duration": 6000, "size": 999}],
    "h264": [{"masterUrl": "http://sns-v1.rednotecdn.com/stream/a_264.mp4", "videoCodec": "h264", "height": 1280, "duration": 6000, "size": len(DATA), "x": None}]}}}}}
PAGE = ('<html><head><meta property="og:title" content="Test note - rednote"><meta property="og:video" content="https://sns-v1.rednotecdn.com/stream/og.mp4"></head>'
        '<script>window.__INITIAL_STATE__=' + json.dumps(state).replace("null", "undefined") + '</script></html>')
seen = []
def handler(req: httpx.Request) -> httpx.Response:
    seen.append(str(req.url))
    h, path = req.url.host, req.url.path
    if h == "xhslink.com" and path == "/o/good": return httpx.Response(302, headers={"location": "https://www.xiaohongshu.com/discovery/item/1?x=1"})
    if h == "www.xiaohongshu.com": return httpx.Response(302, headers={"location": "https://www.rednote.com/discovery/item/1"})
    if h == "www.rednote.com": return httpx.Response(200, text=PAGE)
    if h == "xhslink.com" and path == "/o/evil": return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    if h == "xhslink.com" and path == "/o/photo": return httpx.Response(200, text="<html><meta property='og:title' content='x'></html>")
    if h == "sns-v1.rednotecdn.com": return httpx.Response(200, content=DATA)
    return httpx.Response(500)
real_client = httpx.Client
lf.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"})

ok(lf.find_link("62 小明发布了一篇小红书笔记 http://xhslink.com/o/good 复制后打开【小红书】App查看") == "http://xhslink.com/o/good", "the link is picked out of the copied share sentence")
for bad in ("https://example.com/video.mp4", "hello", "http://xhslink.com.evil.io/o/x", "file:///etc/passwd"):
    try: lf.find_link(bad); ok(False, f"refuses {bad}")
    except lf.LinkError: ok(True, f"not a RedNote link: {bad}")
info = lf.parse_page(PAGE)
ok(info["video_url"].endswith("a_264.mp4") and info["duration"] == 6 and info["title"] == "Test note", f"page parsed: H.264 stream chosen, {info['duration']}s, title '{info['title']}'")
os.makedirs(f"{tmp}/up", exist_ok=True)
got = lf.fetch("http://xhslink.com/o/good", f"{tmp}/up", 7, 50)
ok(os.path.getsize(got["path"]) == len(DATA) and lf.path_of(f"{tmp}/up", 7, got["id"]) == got["path"], "video downloaded for its owner")
ok(lf.path_of(f"{tmp}/up", 8, got["id"]) is None and lf.path_of(f"{tmp}/up", 7, "../../etc/passwd") is None, "another user / a made-up id gets nothing")
seen.clear()
try: lf.fetch("http://xhslink.com/o/evil", f"{tmp}/up", 7, 50); ok(False, "redirect outside RedNote refused")
except lf.LinkError: ok(not any("169.254" in u for u in seen), "a redirect to a non-RedNote address is refused and never contacted")
try: lf.fetch("http://xhslink.com/o/photo", f"{tmp}/up", 7, 50); ok(False, "photo post")
except lf.LinkError as e: ok("No video" in str(e), "a post without a video gives a clear message")
try: lf.fetch("http://xhslink.com/o/good", f"{tmp}/up", 7, 0); ok(False, "size cap")
except lf.LinkError as e: ok("larger than" in str(e) and len([n for n in os.listdir(f"{tmp}/up") if n.startswith("link_")]) == 1, "over the size limit: refused, nothing left on disk")

# ---- API ----
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
gemini_dub.dub = lambda path, target, **kw: ("zh", gemini_dub.finish_segments([{"start": 0.5, "end": 4.0, "source_text": "x", "translated_text": TEXT}], kw.get("scene_cuts") or []))
pipeline.detect_text_regions = lambda v, d: {"subtitle": None, "watermarks": [], "line_height": None, "presence": 0}
c = TestClient(app)
H = {"Authorization": "Bearer " + c.post("/api/auth/register", json={"email": "l@example.com", "password": "password123"}).json()["token"]}
H2 = {"Authorization": "Bearer " + c.post("/api/auth/register", json={"email": "m@example.com", "password": "password123"}).json()["token"]}
ok(c.post("/api/link/fetch", json={"url": "https://example.com/a.mp4"}, headers=H).status_code == 400, "API refuses a non-RedNote link")
r = c.post("/api/link/fetch", json={"url": "看看这个 http://xhslink.com/o/good 复制"}, headers=H)
ok(r.status_code == 200 and abs(r.json()["seconds"] - 6) < 0.3 and r.json()["title"] == "Test note", f"API fetched the video ({r.json().get('seconds')}s)")
lid = r.json()["id"]
f = c.get(f"/api/link/{lid}/file", headers=H)
ok(f.status_code == 200 and len(f.content) == len(DATA), "the owner can download the file for the preview")
ok(c.get(f"/api/link/{lid}/file", headers=H2).status_code == 404 and c.get(f"/api/link/{lid}/file").status_code in (401, 403), "nobody else can")
ok(c.post("/api/jobs", headers=H, data={"voice_type": "su", "link_id": "0" * 32}).status_code == 400, "an unknown link id is refused")
j = c.post("/api/jobs", headers=H, data={"voice_type": "su", "fit_translation": "false", "link_id": lid, "link_title": r.json()["title"]})
ok(j.status_code == 200, f"a video is started from the link without uploading ({j.text[:120]})")
while True:
    job = c.get(f"/api/jobs/{j.json()['job_id']}", headers=H).json()
    if job["status"] in ("done", "error", "cancelled"): break
    time.sleep(1)
ok(job["status"] == "done" and (job["result"].get("video_url") or job["result"].get("video_file")), f"the video finished ({job.get('error')})")
ok(c.get(f"/api/link/{lid}/file", headers=H).status_code == 200, "the fetched file is still kept (another try needs no new fetch)")
codes = [c.post("/api/link/fetch", json={"url": "http://xhslink.com/o/photo"}, headers=H).status_code for _ in range(5)]
ok(429 in codes, f"too many links in a minute are slowed down ({codes})")

# ---- YouTube / TikTok (yt-dlp replaced by a fake) ----
ok([lf.site_of(u) for u in ("https://youtu.be/abc", "https://www.youtube.com/shorts/abc", "https://vm.tiktok.com/ZS1/", "https://www.tiktok.com/@a/video/1",
                            "http://xhslink.com/o/good", "https://youtube.com.evil.io/watch", "https://example.com/tiktok.com")]
   == ["YouTube", "YouTube", "TikTok", "TikTok", "RedNote", "", ""], "YouTube, TikTok and RedNote addresses are told apart; look-alikes refused")
calls = []
class FakeYDL:
    info = {"title": "A clip", "duration": 6}
    def __init__(self, opts): self.opts = opts; calls.append(opts)
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def extract_info(self, url, download=False):
        if "boom" in url: raise RuntimeError("ERROR: Sign in to confirm you're not a bot")
        return dict(self.info, **({"_type": "playlist", "entries": [1]} if "list" in url else {}), **({"is_live": True} if "live" in url else {}))
    def process_ie_result(self, info, download=True):
        open(self.opts["outtmpl"].replace("%(ext)s", "mp4"), "wb").write(DATA)
class FakeYT:
    YoutubeDL = FakeYDL
    class utils:
        download_range_func = staticmethod(lambda chapters, ranges: ("ranges", ranges))
lf._yt_dlp = lambda: FakeYT
g = lf.fetch("watch this https://youtu.be/abc ok", f"{tmp}/up", 7, 50, 600)
ok(g["site"] == "YouTube" and g["title"] == "A clip" and os.path.getsize(g["path"]) == len(DATA) and lf.path_of(f"{tmp}/up", 7, g["id"]) == g["path"], "a YouTube link is fetched to the owner's file")
ok(calls[-1]["allowed_extractors"] == lf.SITE_EXTRACTORS and calls[-1]["noplaylist"] and "download_ranges" not in calls[-1], "only the single-video extractors are allowed; a short video is fetched whole")
FakeYDL.info = {"title": "Long", "duration": 3600}
g = lf.fetch("https://www.tiktok.com/@a/video/1", f"{tmp}/up", 7, 50, 600)
ok(calls[-1].get("download_ranges") == ("ranges", [(0, 602)]) and g["site"] == "TikTok", "a video longer than the limit is fetched only up to the limit")
before = sorted(os.listdir(f"{tmp}/up"))
for url, word in (("https://youtu.be/list", "ONE YouTube video"), ("https://youtu.be/live", "Live"), ("https://youtu.be/boom", "did not allow")):
    try: lf.fetch(url, f"{tmp}/up", 7, 50, 600); ok(False, url)
    except lf.LinkError as e: ok(word in str(e), f"refused with a clear message: {e}")
try: lf.fetch("https://youtu.be/abc", f"{tmp}/up", 7, 0, 600); ok(False, "size cap")
except lf.LinkError as e: ok("larger than" in str(e), "too big a YouTube video is refused")
ok(sorted(os.listdir(f"{tmp}/up")) == before, "refused links leave nothing on disk")
FakeYDL.info = {"title": "A clip", "duration": 6}
r = c.post("/api/link/fetch", json={"url": "https://www.youtube.com/watch?v=abc"}, headers=H2)
ok(r.status_code == 200 and r.json()["site"] == "YouTube" and abs(r.json()["seconds"] - 6) < 0.3, f"API fetches a YouTube link ({r.text[:100]})")
print("ALL OK")
