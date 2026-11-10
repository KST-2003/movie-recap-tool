"""Request guard (ASGI middleware): cheap checks that run BEFORE any request body is read or any route code runs.

 1. Admin allow-list: `ADMIN_ALLOWED_IPS` (comma separated IPs / CIDRs, empty = off). /api/admin/* answers 404 to every other address, so the
    owner dashboard can be limited to an office / VPN even though it shares the public API host.
 2. Uploads need a login first: POST /api/jobs without a validly signed, unexpired token is refused (401) before a single byte of the (up to
    1 GB) body is read. FastAPI otherwise parses the whole multipart body before it checks who is asking.
 3. Body size: Content-Length above the limit is refused (413) at once; a body without Content-Length (chunked) is counted while it streams and
    cut off at the limit. Upload route: MAX_UPLOAD_MB + room for the logo and form fields; /api/auth/*: 64 KB; everything else: 4 MB.
 4. Response headers on /api/*: nosniff, no referrer, no framing, a deny-all CSP, and `no-store` on anything that carries a token, an account or a job
    (never cached by a browser or a shared cache). Headers an endpoint sets itself (e.g. the 1-week cache of voice samples) are left alone.
Put it BEFORE the CORS middleware in main.py so its 401 / 413 answers still carry the CORS headers (else the browser shows a bare network error)."""
import ipaddress
import json
import os

from starlette.requests import Request

import auth
import ratelimit
from config import MAX_UPLOAD_MB

UPLOAD_LIMIT = (MAX_UPLOAD_MB + 25) * 1024 * 1024   # video + logo (20 MB) + form fields
AUTH_LIMIT = 64 * 1024
DEFAULT_LIMIT = 4 * 1024 * 1024                      # largest JSON body: a re-render of 600 lines is about 1.7 MB

_BASE_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"no-referrer",
    b"x-frame-options": b"DENY",
}
_JSON_ONLY_HEADERS = {   # a deny-all CSP on a video / audio response could blank a player opened directly in a tab, so JSON answers only
    b"content-security-policy": b"default-src 'none'; frame-ancestors 'none'",
}
_NO_STORE_PREFIXES = ("/api/auth/", "/api/jobs", "/api/usage", "/api/admin/")


class _TooLarge(Exception):
    pass


def _admin_networks() -> list:
    out = []
    for item in os.getenv("ADMIN_ALLOWED_IPS", "").split(","):
        item = item.strip()
        if item:
            try:
                out.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                print(f"[guard] ignoring bad ADMIN_ALLOWED_IPS entry: {item!r}", flush=True)
    return out


def _limit_for(method: str, path: str) -> int:
    if method == "POST" and path == "/api/jobs":
        return UPLOAD_LIMIT
    if path.startswith("/api/auth/"):
        return AUTH_LIMIT
    return DEFAULT_LIMIT


async def _reply(send, status: int, detail: str, headers: dict | None = None):
    body = json.dumps({"detail": detail}).encode()
    hdrs = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    hdrs += [(k.encode(), v.encode()) for k, v in (headers or {}).items()]
    hdrs += [(k, v) for k, v in {**_BASE_HEADERS, **_JSON_ONLY_HEADERS}.items()] + [(b"cache-control", b"no-store")]
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": body})


class RequestGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]

        # 1. admin allow-list
        if path.startswith("/api/admin/"):
            nets = _admin_networks()
            if nets:
                try:
                    ip = ipaddress.ip_address(ratelimit.client_ip(Request(scope)))
                    allowed = any(ip in n for n in nets)
                except ValueError:
                    allowed = False
                if not allowed:
                    return await _reply(send, 404, "Not found")

        # 2. an upload needs a signed, unexpired token before its body is read (the endpoint still checks the account)
        if method == "POST" and path == "/api/jobs":
            header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            token = header[7:] if header.lower().startswith("bearer ") else ""
            try:
                auth._decode(token)
            except Exception:
                return await _reply(send, 401, "Please log in.")

        # 3. body size
        limit = _limit_for(method, path)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None:
            try:
                if int(length) > limit:
                    return await _reply(send, 413, f"The request is too large (limit {limit // (1024 * 1024) or 1} MB).")
            except ValueError:
                return await _reply(send, 400, "Bad request.")
        received = 0

        async def counted_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True   # remembered: FastAPI wraps errors raised while it parses a body into its own 400, which we must replace
                    raise _TooLarge()
            return message

        started = False
        too_large = False
        replied = False
        too_large_text = f"The request is too large (limit {limit // (1024 * 1024) or 1} MB)."

        # 4. headers on the way out
        async def guarded_send(message):
            nonlocal started, replied
            if too_large:   # whatever the app answers after we cut the body off is replaced by one clean 413
                if not replied and not started:
                    replied = True
                    await _reply(send, 413, too_large_text)
                return
            if message["type"] == "http.response.start":
                started = True
                if path.startswith("/api/"):
                    have = {k.lower() for k, _ in message.get("headers", [])}
                    ctype = next((v for k, v in message.get("headers", []) if k.lower() == b"content-type"), b"application/json")
                    wanted = {**_BASE_HEADERS, **(_JSON_ONLY_HEADERS if ctype.startswith(b"application/json") else {})}
                    extra = [(k, v) for k, v in wanted.items() if k not in have]
                    if path.startswith(_NO_STORE_PREFIXES) and b"cache-control" not in have:
                        extra.append((b"cache-control", b"no-store"))
                    message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except _TooLarge:
            pass
        if too_large and not replied and not started:
            await _reply(send, 413, too_large_text)
