"""Email/password accounts, bearer tokens (JWT) and short-lived signed file URLs."""
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sqlalchemy import select

from config import DATA_DIR, TRUST_PROXY
from db import Session, User, UserDevice, utcnow

TOKEN_DAYS = int(os.getenv("TOKEN_DAYS", "14"))


def _secret() -> bytes:
    env = os.getenv("SECRET_KEY")
    if env:
        return env.encode()
    path = os.path.join(DATA_DIR, "secret.key")  # dev fallback: generated once, kept next to the database
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
        os.chmod(path, 0o600)
    return open(path).read().encode()


SECRET = _secret()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _pw_mark(user: User) -> str:
    """Changes whenever the password changes, so a regenerated password signs every old session out."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:10]


def make_token(user: User, device_id: str | None = None) -> str:
    claims = {"sub": str(user.id), "exp": int(time.time()) + TOKEN_DAYS * 86400, "pw": _pw_mark(user)}
    if device_id:
        claims["did"] = device_id
    return jwt.encode(claims, SECRET, algorithm="HS256")


# ---- who is calling: IP, browser, device ----

def client_ip(request: Request) -> str:
    """The visitor's IP. Behind Nginx set TRUST_PROXY=1 (and let Nginx send X-Forwarded-For); never trust the header otherwise."""
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.headers.get("x-real-ip", "").strip()
        if fwd:
            return fwd[:64]
    return request.client.host if request.client else "?"


def parse_ua(ua: str) -> tuple[str, str]:
    """(browser, operating system) from a User-Agent string. A web page cannot read the real device name, so this is the best label."""
    ua = ua or ""
    os_name = ("iPhone" if "iPhone" in ua else "iPad" if "iPad" in ua else "Android" if "Android" in ua else "Windows" if "Windows" in ua
               else "macOS" if "Mac OS X" in ua or "Macintosh" in ua else "Linux" if "Linux" in ua else "Unknown")
    browser = ("Edge" if re.search(r"Edg(e|A|iOS)?/", ua) else "Opera" if re.search(r"OPR/|Opera", ua) else "Samsung Internet" if "SamsungBrowser" in ua
               else "Firefox" if re.search(r"Firefox/|FxiOS/", ua) else "Chrome" if re.search(r"Chrome/|CriOS/", ua)
               else "Safari" if "Safari/" in ua else "Unknown")
    return browser, os_name


def clean_device_id(value: str | None) -> str:
    return value if value and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value) else "unknown"


STATUS_MESSAGES = {
    "paused": "Your account is paused. Please contact the admin.",
    "deactivated": "Your account is deactivated. Please contact the admin.",
    "banned": "Your account has been banned. Please contact the admin.",
}
DEVICE_FULL = "This login is already in use on another device. Ask the admin to reset it."
DEVICE_REMOVED = "You were signed out because this login was used on another device. Please log in again."   # also shown after an admin removes the device


def register_device(s, user: User, device_id: str, request: Request) -> None:
    """Called at login. A known device just updates its details; a new one takes a slot, signing out the least recently used device when the login is at its limit (device_limit 0 = unlimited)."""
    ip = client_ip(request)
    browser, os_name = parse_ua(request.headers.get("user-agent", ""))
    row = s.execute(select(UserDevice).where(UserDevice.user_id == user.id, UserDevice.device_id == device_id)).scalar_one_or_none()
    if row is None:
        count = len(s.execute(select(UserDevice.id).where(UserDevice.user_id == user.id)).all())
        if user.device_limit and count >= user.device_limit:
            # Newest login wins (owner's rule, 2026-11-13): the device(s) used longest ago are signed out to make room, so a login
            # limited to ONE device works on one device AT A TIME and nobody has to ask the admin after changing phones.
            # (Before: the new device was refused with DEVICE_FULL until the admin freed the slot.)
            old = s.execute(select(UserDevice).where(UserDevice.user_id == user.id)
                            .order_by(UserDevice.last_seen.asc(), UserDevice.id.asc())).scalars().all()
            for gone in old[: count - user.device_limit + 1]:
                s.delete(gone)
        row = UserDevice(user_id=user.id, device_id=device_id, first_ip=ip)
        s.add(row)
    row.name, row.browser, row.os, row.ip, row.last_seen = f"{browser} on {os_name}", browser, os_name, ip, utcnow()


_bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    try:
        claims = jwt.decode(creds.credentials, SECRET, algorithms=["HS256"])
        user_id = int(claims["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    with Session() as s:
        user = s.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Account unavailable.")
        if user.status != "active":
            raise HTTPException(status_code=401, detail=STATUS_MESSAGES.get(user.status, "Account unavailable."))
        if claims.get("pw") and claims["pw"] != _pw_mark(user):
            raise HTTPException(status_code=401, detail="Your password was changed. Please log in again.")
        did = claims.get("did")
        if did:   # tokens without a device (made by scripts/tests) are not device-checked
            row = s.execute(select(UserDevice).where(UserDevice.user_id == user.id, UserDevice.device_id == did)).scalar_one_or_none()
            if row is None:
                raise HTTPException(status_code=401, detail=DEVICE_REMOVED)
            ip = client_ip(request)
            last = row.last_seen if row.last_seen.tzinfo else row.last_seen.replace(tzinfo=utcnow().tzinfo)
            if row.ip != ip or utcnow() - last > timedelta(seconds=60):   # not a write on every poll
                row.ip, row.last_seen = ip, utcnow()
                s.commit()
    return user


# ---- signed file links (a <video> tag cannot send an Authorization header) ----

def sign_file(filename: str, ttl: int) -> tuple[int, str]:
    exp = int(time.time()) + ttl
    sig = hmac.new(SECRET, f"{filename}.{exp}".encode(), hashlib.sha256).hexdigest()
    return exp, sig


def check_signature(filename: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    good = hmac.new(SECRET, f"{filename}.{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)


# ---- minimal brute-force guard for login/signup (per IP, in-memory; use a gateway/Redis for multi-replica) ----

_hits: dict[str, list[float]] = {}


def rate_limit(request: Request, limit: int = 10, window: int = 600):
    ip = client_ip(request)
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < window]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    recent.append(now)
    _hits[ip] = recent
