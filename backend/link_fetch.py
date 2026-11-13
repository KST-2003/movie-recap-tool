"""Get a video from a RedNote (Xiaohongshu) share link instead of an upload.

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


class LinkError(Exception):
    """Something the user can be told (wrong link, post has no video, RedNote refused, too big)."""


def _host_ok(url: str, hosts: tuple) -> bool:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    return p.scheme in ("http", "https") and any(h == x or h.endswith("." + x) for x in hosts)


def find_link(text: str) -> str:
    """The share text copied from the app is a sentence with the link inside: take the first RedNote address."""
    for m in re.finditer(r"https?://[^\s　，。！]+", text or ""):
        url = m.group(0).rstrip(".,;:!?)\"'")
        if _host_ok(url, PAGE_HOSTS):
            return url
    raise LinkError("Paste a RedNote (Xiaohongshu) share link.")


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


def fetch(text: str, directory: str, owner: int, max_mb: int) -> dict:
    """Resolve the link and download the video into `directory`. -> {id, path, duration, size, title}."""
    url = find_link(text)
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
    return {"id": link_id, "path": path, "duration": info["duration"], "size": size, "title": info["title"]}


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
