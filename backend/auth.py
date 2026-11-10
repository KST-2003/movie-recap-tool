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


# scrypt cost. N=2^15, r=8, p=3 is one of the equivalent settings OWASP lists (32 MiB of memory, about 0.3 s); the old code used N=2^14, p=1,
# which is about 6 times cheaper to attack. The cost is written INTO every stored hash, so it can be raised later and old hashes keep working;
# a user's hash is upgraded the next time they log in with the right password (see needs_rehash / main.login).
SCRYPT_LOG2_N = int(os.getenv("PASSWORD_SCRYPT_LOG2_N", "15"))
SCRYPT_R = 8
SCRYPT_P = int(os.getenv("PASSWORD_SCRYPT_P", "3"))
_SCRYPT_MAXMEM = 256 * 1024 * 1024
_LEGACY = (14, 8, 1)   # hashes written before 2026-11-10: "salt_hex$digest_hex" with these settings and a 64-byte digest


def _scrypt(password: str, salt: bytes, log2_n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** log2_n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=dklen)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P, 32)
    return f"scrypt${SCRYPT_LOG2_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _parse(stored: str) -> tuple[int, int, int, bytes, bytes]:
    """-> (log2 N, r, p, salt, digest) of a stored hash, new or legacy. Raises on anything else, and on settings no honest hash uses
    (a damaged row must not make the server allocate gigabytes)."""
    parts = stored.split("$")
    if len(parts) == 6 and parts[0] == "scrypt":
        log2_n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, digest = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    elif len(parts) == 2:
        (log2_n, r, p), salt, digest = _LEGACY, bytes.fromhex(parts[0]), bytes.fromhex(parts[1])
    else:
        raise ValueError("unknown hash format")
    if not (10 <= log2_n <= 20 and 1 <= r <= 16 and 1 <= p <= 16 and 8 <= len(salt) <= 64 and 16 <= len(digest) <= 128):
        raise ValueError("hash settings out of range")
    return log2_n, r, p, salt, digest


def verify_password(password: str, stored: str) -> bool:
    try:
        log2_n, r, p, salt, digest = _parse(stored)
        return hmac.compare_digest(_scrypt(password, salt, log2_n, r, p, len(digest)), digest)
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True for a hash written with other settings than today's (all old accounts, until their next login)."""
    try:
        log2_n, r, p, _, _ = _parse(stored)
    except Exception:
        return False
    return (log2_n, r, p) != (SCRYPT_LOG2_N, SCRYPT_R, SCRYPT_P)


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

# Its own key, derived from the secret: a file-link signature can never be mistaken for (or turned into) a login token signature.
_FILE_KEY = hmac.new(SECRET, b"movie-recap-tool/signed-file-links/v1", hashlib.sha256).digest()


def sign_file(filename: str, ttl: int) -> tuple[int, str]:
    exp = int(time.time()) + ttl
    sig = hmac.new(_FILE_KEY, f"{filename}.{exp}".encode(), hashlib.sha256).hexdigest()
    return exp, sig


def check_signature(filename: str, exp: int, sig: str) -> bool:
    if exp < time.time():
        return False
    good = hmac.new(_FILE_KEY, f"{filename}.{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(good, sig)
