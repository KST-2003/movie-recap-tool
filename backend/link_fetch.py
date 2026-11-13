"""Get a video from a RedNote (Xiaohongshu), YouTube or TikTok link instead of an upload.

RedNote = our own code below (the first part of this text). YouTube and TikTok = the yt-dlp library (`_site_fetch`, 2026-11-14):
only the single-video extractors are loaded, so channels, playlists, searches and every other site are refused; a video longer
than the limit is fetched only up to the limit; H.264 + AAC in MP4, at most 1080p. Both sites change often and block servers
(YouTube: "Sign in to confirm you're not a bot" on data-centre addresses): keep yt-dlp up to date, upload stays the fallback.

The share link (xhslink.com/...) redirects to the note's page; the page carries the video file's address (og:video and the
note's JSON), its length and size. Checked from the server on 2026-11-13 with one real link: no login, no block, 13.7 MB in 0.4 s;
the file carries RedNote's corner watermark. RedNote can change or block this at any time: every failure is a `LinkError` with a
text for the user ("upload the file instead"), never a crash.

Safety: only RedNote hosts are ever contacted (the share link, every redirect hop and the video file are checked against fixed
host lists), so a pasted address cannot make the server fetch anything else; the download is size-capped while streaming."""
import html
import json
import os
import re
import time
import uuid
from urllib.parse import urljoin, urlparse

import httpx

PAGE_HOSTS = ("xhslink.com", "xiaohongshu.com", "rednote.com")
VIDEO_HOSTS = ("rednotecdn.com", "xhscdn.com", "xiaohongshu.com", "rednote.com")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
KEEP_SECONDS = int(os.getenv("LINK_KEEP_SECONDS", "7200"))      # a fetched file waits this long for "Generate"
MAX_HOPS = 6
SITE_HOSTS = {"YouTube": ("youtube.com", "youtu.be"), "TikTok": ("tiktok.com",)}      # fetched with yt-dlp
SITE_EXTRACTORS = ["youtube", "tiktok", r"vm\.tiktok"]     # yt-dlp extractor names (single videos only, nothing else is loaded)
SITE_FORMAT = ("bv*[vcodec^=avc1][height<=1080]+ba[ext=m4a]/b[vcodec^=avc1][height<=1080]/b[vcodec^=h264][height<=1080]/"
               "b[ext=mp4][height<=1080]/b[height<=1080]/b")     # H.264 first: every browser and phone decodes it


class LinkError(Exception):
    """Something the user can be told (wrong link, post has no video, RedNote refused, too big)."""


def _host_ok(url: str, hosts: tuple) -> bool:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and any(h == x or h.endswith("." + x) for x in hosts)


def find_link(text: str) -> str:
    """The share text copied from the app is a sentence with the link inside: take the first address of a site we support."""
    for m in re.finditer(r"https?://[^\s　，。！]+", text or ""):
        url = m.group(0).rstrip(".,;:!?)\"'")
        if site_of(url):
            return url
    raise LinkError("Paste a RedNote, YouTube or TikTok link.")


def site_of(url: str) -> str:
    """'RedNote' | 'YouTube' | 'TikTok' | '' (not a site we fetch from)."""
    if _host_ok(url, PAGE_HOSTS):
        return "RedNote"
    return next((site for site, hosts in SITE_HOSTS.items() if _host_ok(url, hosts)), "")


def _yt_dlp():
    import yt_dlp
    return yt_dlp


def _site_fetch(url: str, site: str, base: str, max_mb: int, max_seconds: float) -> dict:
    """YouTube / TikTok through yt-dlp -> {path (base + '.mp4'), duration, size, title}."""
    try:
        yt_dlp = _yt_dlp()
    except ImportError as exc:
        raise LinkError(f"{site} links are not available right now. Please upload the video file instead.") from exc
    limit = max_mb * 1024 * 1024
    class Quiet:      # yt-dlp prints its errors itself: we log one line in the except block instead
        debug = warning = error = staticmethod(lambda *a, **k: None)
    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "cachedir": False, "logger": Quiet,
            "allowed_extractors": SITE_EXTRACTORS, "format": SITE_FORMAT, "merge_output_format": "mp4",
            "outtmpl": base + ".%(ext)s", "socket_timeout": 25, "retries": 2, "fragment_retries": 2, "max_filesize": limit}
    made = lambda: [os.path.join(os.path.dirname(base), n) for n in os.listdir(os.path.dirname(base))
                    if n.startswith(os.path.basename(base) + ".")]
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") in ("playlist", "multi_video") or info.get("entries"):
            raise LinkError(f"Paste the link of ONE {site} video (not a channel or a playlist).")
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise LinkError(f"Live {site} videos cannot be fetched. Please upload the video file instead.")
        duration = float(info.get("duration") or 0)
        cut = bool(max_seconds and duration > max_seconds + 5)
        if cut:      # a long video: fetch only the part we will use (the upload rule keeps the first minutes anyway)
            opts["download_ranges"] = yt_dlp.utils.download_range_func(None, [(0, max_seconds + 2)])
        else:
            size = info.get("filesize") or info.get("filesize_approx") or 0
            if size > limit:
                raise LinkError(f"This video is larger than {max_mb} MB.")
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_ie_result(info, download=True)
        files = [p for p in made() if not p.endswith((".part", ".ytdl"))]
        if not files or os.path.getsize(files[0]) < 10_000:
            raise LinkError(f"{site} did not give the video file. Please upload the video file instead.")
        size = os.path.getsize(files[0])
        if size > limit:
            raise LinkError(f"This video is larger than {max_mb} MB.")
        os.replace(files[0], base + ".mp4")
        return {"path": base + ".mp4", "duration": min(duration, max_seconds + 2) if cut else (duration or None), "size": size,
                "title": str(info.get("title") or "").strip()[:100]}
    except LinkError:
        for p in made():
            os.remove(p)
        raise
    except Exception as exc:      # yt-dlp raises many kinds (DownloadError, ExtractorError, ...): none may crash the request
        for p in made():
            os.remove(p)
        print(f"[link] {site}: {str(exc)[:300]}", flush=True)
        text = str(exc).lower()
        if "no suitable extractor" in text or "unsupported url" in text:
            raise LinkError(f"Paste the link of ONE {site} video (not a channel or a playlist).") from exc
        if "sign in" in text or "not a bot" in text or "login" in text or "blocked" in text:
            raise LinkError(f"{site} did not allow our server to get this video. Please upload the video file instead.") from exc
        if "private" in text or "unavailable" in text or "removed" in text or "not available" in text:
            raise LinkError(f"{site} did not give this video (it may be private, removed or not available in our region). Please upload the video file instead.") from exc
        raise LinkError(f"{site} did not give the video. Please upload the video file instead.") from exc


def _page(url: str, client: httpx.Client) -> str:
    for _ in range(MAX_HOPS):
        if not _host_ok(url, PAGE_HOSTS):
            raise LinkError("This link does not lead to a RedNote post.")
        host = (urlparse(url).hostname or "").lower()
        if host in ("xiaohongshu.com", "www.xiaohongshu.com"):
            # The share link sends us to xiaohongshu.com, which only redirects on to rednote.com outside China, and from our
            # server that hop took 25 s (measured 2026-11-13; rednote.com directly: 0.8 s, same page). Try rednote.com first.
            try:
                direct = client.get(url.replace("://" + urlparse(url).netloc + "/", "://www.rednote.com/", 1))
                if direct.status_code == 200 and parse_page(direct.text)["video_url"]:
                    return direct.text
            except httpx.HTTPError:
                pass
        r = client.get(url)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        if r.status_code != 200:
            raise LinkError("RedNote did not open this link. Please upload the video file instead.")
        return r.text
    raise LinkError("RedNote did not open this link. Please upload the video file instead.")


def parse_page(page: str) -> dict:
    """-> {video_url, duration (s) or None, size (bytes) or None, title}. Pure (tested offline with a saved page)."""
    info = {"video_url": None, "duration": None, "size": None, "title": ""}
    m = re.search(r'<meta[^>]+(?:property|name)="og:title"[^>]+content="([^"]*)"', page)
    if m:
        info["title"] = re.sub(r"\s*-\s*(rednote|小红书)\s*$", "", html.unescape(m.group(1)), flags=re.I).strip()[:100]
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", page, re.S)
    if m:
        try:
            best = None

            def walk(o):
                nonlocal best
                if isinstance(o, dict):
                    if isinstance(o.get("masterUrl"), str) and o["masterUrl"].startswith("http"):
                        # prefer H.264 (every browser and phone decodes it), then the biggest picture
                        key = (o.get("videoCodec") == "h264", o.get("height") or 0, o.get("avgBitrate") or 0)
                        if best is None or key > best[0]:
                            best = (key, o)
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)
            walk(json.loads(re.sub(r"\bundefined\b", "null", m.group(1))))
            if best:
                o = best[1]
                info["video_url"] = o["masterUrl"]
                info["duration"] = (o.get("duration") or 0) / 1000 or None
                info["size"] = o.get("size") or None
        except Exception:
            pass
    if not info["video_url"]:
        m = re.search(r'<meta[^>]+(?:property|name)="og:video"[^>]+content="([^"]+)"', page)
        if m:
            info["video_url"] = html.unescape(m.group(1))
    return info


def fetch(text: str, directory: str, owner: int, max_mb: int, max_seconds: float = 0) -> dict:
    """Resolve the link and download the video into `directory`. -> {id, path, duration, size, title, site}.
    `max_seconds`: a longer YouTube / TikTok video is fetched only up to there (0 = whole video)."""
    url = find_link(text)
    site = site_of(url)
    if site != "RedNote":
        link_id = uuid.uuid4().hex
        got = _site_fetch(url, site, os.path.join(directory, f"link_{owner}_{link_id}"), max_mb, max_seconds)
        return {"id": link_id, "site": site, **got}
    try:
        with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "en,zh;q=0.8"}, timeout=25, follow_redirects=False) as client:
            info = parse_page(_page(url, client))
            video = info["video_url"]
            if not video:
                raise LinkError("No video was found in this post (it may be a photo post, private or removed). Please upload the video file instead.")
            if not _host_ok(video, VIDEO_HOSTS):
                raise LinkError("This link's video cannot be fetched. Please upload the video file instead.")
            limit = max_mb * 1024 * 1024
            if info["size"] and info["size"] > limit:
                raise LinkError(f"This video is larger than {max_mb} MB.")
            link_id = uuid.uuid4().hex
            path = os.path.join(directory, f"link_{owner}_{link_id}.mp4")
            size = 0
            try:
                for _ in range(MAX_HOPS):
                    with client.stream("GET", video, timeout=httpx.Timeout(25, read=120)) as r:
                        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                            video = urljoin(video, r.headers["location"])
                            if not _host_ok(video, VIDEO_HOSTS):
                                raise LinkError("This link's video cannot be fetched. Please upload the video file instead.")
                            continue
                        if r.status_code != 200:
                            raise LinkError("RedNote did not give the video file. Please upload the video file instead.")
                        with open(path, "wb") as f:
                            for chunk in r.iter_bytes(1024 * 1024):
                                size += len(chunk)
                                if size > limit:
                                    raise LinkError(f"This video is larger than {max_mb} MB.")
                                f.write(chunk)
                        break
                else:
                    raise LinkError("RedNote did not give the video file. Please upload the video file instead.")
                if size < 10_000:
                    raise LinkError("RedNote did not give the video file. Please upload the video file instead.")
            except BaseException:
                if os.path.exists(path):
                    os.remove(path)
                raise
    except LinkError:
        raise
    except httpx.HTTPError as exc:
        raise LinkError("RedNote could not be reached. Please try again, or upload the video file instead.") from exc
    return {"id": link_id, "path": path, "duration": info["duration"], "size": size, "title": info["title"], "site": "RedNote"}


def path_of(directory: str, owner: int, link_id: str) -> str | None:
    """The fetched file of this user, or None (unknown id, someone else's, already cleaned up)."""
    if not re.fullmatch(r"[0-9a-f]{32}", link_id or ""):
        return None
    path = os.path.join(directory, f"link_{owner}_{link_id}.mp4")
    return path if os.path.isfile(path) else None


def sweep(directory: str) -> None:
    """Delete fetched files nobody generated from."""
    now = time.time()
    try:
        for name in os.listdir(directory):
            if name.startswith("link_"):
                p = os.path.join(directory, name)
                if now - os.path.getmtime(p) > KEEP_SECONDS:
                    os.remove(p)
    except OSError:
        pass
