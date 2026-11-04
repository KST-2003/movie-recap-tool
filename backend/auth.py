"""Email/password accounts, bearer tokens (JWT) and short-lived signed file URLs."""
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import DATA_DIR
from db import Session, User

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


def make_token(user: User) -> str:
    return jwt.encode({"sub": str(user.id), "exp": int(time.time()) + TOKEN_DAYS * 86400}, SECRET, algorithm="HS256")


_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    if creds is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    try:
        user_id = int(jwt.decode(creds.credentials, SECRET, algorithms=["HS256"])["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    with Session() as s:
        user = s.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable.")
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
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _hits.get(ip, []) if now - t < window]
    if len(recent) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    recent.append(now)
    _hits[ip] = recent
