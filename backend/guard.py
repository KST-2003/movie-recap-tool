"""Request guard (ASGI middleware): cheap checks that run BEFORE any request body is read or any route code runs.

Why (security audit 2026-11-19, finding 1): FastAPI reads and parses a whole request body (a multipart upload of up to 1 GB is spooled to disk)
BEFORE it runs the login dependency, and Nginx accepts 1100 MB on every /api/ route. So anyone on the internet, without an account, could make
the server receive and store gigabytes (POST /api/jobs) or hold huge JSON bodies in memory (POST /api/auth/login). This guard:

 1. Upload routes need a valid, unexpired login token FIRST: without one the answer is 401 and not a byte of the body is read.
    (Only the token's signature and expiry are checked here, no database. The route still checks the account itself.)
 2. Body size per route: a Content-Length above the limit is refused at once (413); a body without Content-Length (chunked) is counted while it
    streams and cut off at the limit. Limits: the upload routes get what they really need (video + logo + form fields ...), /api/auth/* gets 64 KB,
    everything else 8 MB (the biggest JSON body is a re-render of 600 lines).

Plain ASGI (no Starlette internals), so it works on the server's old Starlette 0.36 and on new versions. Add it BEFORE the CORS middleware in
main.py: the last middleware added is the outermost, so CORS then wraps the guard and its 401 / 413 answers still carry the CORS headers
(otherwise the browser shows a bare network error instead of the message)."""
import json
import os
import re

import jwt

import auth
from config import MAX_UPLOAD_MB

MB = 1024 * 1024
DEVICE_VIDEO_MAX_MB = int(os.getenv("DEVICE_VIDEO_MAX_MB", "600"))   # same setting as main.py's device-video route

DEFAULT_LIMIT = int(os.getenv("BODY_LIMIT_DEFAULT_MB", "8")) * MB
AUTH_LIMIT = 64 * 1024

# (method or None for any, path pattern, byte limit, must be logged in before the body is read)
RULES: list[tuple[str | None, "re.Pattern", int, bool]] = [
    ("POST", re.compile(r"^/api/jobs$"), (MAX_UPLOAD_MB + 25) * MB, True),                       # video + logo (20 MB) + form fields
    ("POST", re.compile(r"^/api/jobs/[^/]+/device-video$"), (DEVICE_VIDEO_MAX_MB + 5) * MB, True),   # the finished video of an on-device render
    ("POST", re.compile(r"^/api/topup/requests$"), 10 * MB, True),                                # payment slip (8 MB) + form fields
    ("POST", re.compile(r"^/api/admin/posts(/[^/]+)?$"), 6 * MB, True),                           # banner image (4 MB)
    ("POST", re.compile(r"^/api/admin/payment-qr$"), 5 * MB, True),                               # payment QR (3 MB)
    (None, re.compile(r"^/api/auth/"), AUTH_LIMIT, False),                                        # login / register / me: tiny JSON
]


class _TooLarge(Exception):
    pass


def rule_for(method: str, path: str) -> tuple[int, bool]:
    """(byte limit, login required first) for this request."""
    for m, pattern, limit, login in RULES:
        if (m is None or m == method) and pattern.match(path):
            return limit, login
    return DEFAULT_LIMIT, False


def _mb(limit: int) -> str:
    return f"{limit / MB:g} MB" if limit >= MB else f"{limit // 1024} KB"


async def _reply(send, status: int, detail: str):
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"), (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": body})


def _bearer(headers: dict[bytes, bytes]) -> str:
    value = headers.get(b"authorization", b"").decode("latin-1")
    return value[7:].strip() if value[:7].lower() == "bearer " else ""


def _token_ok(token: str) -> bool:
    if not token:
        return False
    try:
        jwt.decode(token, auth.SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        return True
    except Exception:
        return False


class RequestGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        method, path = scope["method"], scope["path"]
        limit, login_first = rule_for(method, path)
        headers = {k.lower(): v for k, v in scope["headers"]}

        # 1. a login before the body: the upload routes only
        if login_first and not _token_ok(_bearer(headers)):
            return await _reply(send, 401, "Please log in.")

        # 2. body size: the declared length first ...
        too_large_text = f"The request is too large (limit {_mb(limit)})."
        length = headers.get(b"content-length")
        if length is not None:
            try:
                if int(length) > limit:
                    return await _reply(send, 413, too_large_text)
            except ValueError:
                return await _reply(send, 400, "Bad request.")
        if method in ("GET", "HEAD", "OPTIONS", "DELETE") and length in (None, b"0"):
            return await self.app(scope, receive, send)   # nothing to count

        # ... then the real number of bytes, for a body that does not say its length (chunked) or lies about it
        received = 0
        too_large = False
        started = False

        async def counted_receive():
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True   # remembered: FastAPI turns errors raised while it parses a body into its own 400, which we replace below
                    raise _TooLarge()
            return message

        async def guarded_send(message):
            nonlocal started
            if too_large:   # whatever the app answers after we cut the body off is dropped: one clean 413 is sent instead
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except _TooLarge:
            pass
        if too_large and not started:
            await _reply(send, 413, too_large_text)
