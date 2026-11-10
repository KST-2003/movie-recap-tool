"""Email/password accounts, bearer tokens (JWT) and short-lived signed file URLs."""
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import DATA_DIR
from db import Session, User

TOKEN_DAYS = int(os.getenv("TOKEN_DAYS", "14"))                          # normal accounts: how long one token lives
ADMIN_TOKEN_MINUTES = int(os.getenv("ADMIN_TOKEN_MINUTES", "60"))        # admin accounts: short, renewed while the dashboard is open
ADMIN_SESSION_HOURS = int(os.getenv("ADMIN_SESSION_HOURS", "12"))        # admin accounts: renewals stop this long after the password was typed
USER_SESSION_DAYS = int(os.getenv("USER_SESSION_DAYS", "60"))            # normal accounts: same, longer


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


# A real hash to check against when the email is unknown, so "no such user" takes as long as "wrong password" (no account guessing by timing).
DUMMY_HASH = hash_password(secrets.token_hex(8))


def make_token(user: User, session_start: int | None = None) -> str:
    """`tv` = the user's token_version (a bump cancels every older token), `ses` = when the password was typed (renewals keep it, so a
    stolen token cannot be renewed for ever). Admin accounts get short tokens: they are renewed by the dashboard while it is open."""
    now = int(time.time())
    life = ADMIN_TOKEN_MINUTES * 60 if user.is_admin else TOKEN_DAYS * 86400
    return jwt.encode({"sub": str(user.id), "tv": int(user.token_version or 0), "iat": now, "ses": session_start or now, "exp": now + life},
                      SECRET, algorithm="HS256")


def _decode(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]})


_bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    return _user_from(creds)[0]


def _user_from(creds: HTTPAuthorizationCredentials | None) -> tuple[User, dict]:
    if creds is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    try:
        claims = _decode(creds.credentials)
        user_id = int(claims["sub"])
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    with Session() as s:
        user = s.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable.")
    if int(claims.get("tv", 0)) != int(user.token_version or 0):   # tokens from before the last revocation (missing tv = version 0)
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return user, claims


def renewed_token(creds: HTTPAuthorizationCredentials | None) -> tuple[User, str]:
    """A fresh token for a still valid one, unless the session (since the password was typed) is older than its maximum."""
    user, claims = _user_from(creds)
    start = int(claims.get("ses") or claims.get("iat") or time.time())
    limit = (ADMIN_SESSION_HOURS * 3600) if user.is_admin else (USER_SESSION_DAYS * 86400)
    if time.time() - start > limit:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return user, make_token(user, start)


def revoke_tokens(s, user: User) -> None:
    """Cancel every token issued to this user so far (call inside the session that changes the account)."""
    user.token_version = int(user.token_version or 0) + 1


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
