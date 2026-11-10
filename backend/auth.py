"""Email/password accounts, bearer tokens (JWT) and short-lived signed file URLs."""
import hashlib
import hmac
import os
import secrets
import time

import jwt
import base64

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import ratelimit
from config import ADMIN_ORIGINS, CORS_ORIGINS, COOKIE_SAMESITE, COOKIE_SECURE, DATA_DIR
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


def make_token(user: User, session_start: int | None = None, audience: str | None = None) -> str:
    """`tv` = the user's token_version (a bump cancels every older token), `ses` = when the password was typed (renewals keep it, so a
    stolen token cannot be renewed for ever). Admin accounts get short tokens: they are renewed by the dashboard while it is open."""
    now = int(time.time())
    life = ADMIN_TOKEN_MINUTES * 60 if user.is_admin else TOKEN_DAYS * 86400
    audience = audience or ("admin" if user.is_admin else "app")   # which app this session is for (admin API only accepts "admin")
    return jwt.encode({"sub": str(user.id), "tv": int(user.token_version or 0), "iat": now, "ses": session_start or now, "exp": now + life, "scope": audience, "jti": secrets.token_hex(8)},
                      SECRET, algorithm="HS256")


def _decode(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=["HS256"], options={"require": ["exp", "sub"]})


_bearer = HTTPBearer(auto_error=False)

# ---- browser sessions: an httpOnly cookie instead of a token in localStorage ----
# A script injected into a page cannot read an httpOnly cookie, so it cannot steal the session (it can still make requests while the page is open,
# which is what the CSRF token, the Origin checks and the CSP limit). API clients keep using `Authorization: Bearer`.
COOKIE_NAMES = {"app": "session", "admin": "admin_session"}
_CSRF_KEY = hmac.new(SECRET, b"movie-recap-tool/csrf/v1", hashlib.sha256).digest()


def _norm_origin(origin: str | None) -> str:
    return (origin or "").strip().rstrip("/").lower()


_CORS_SET = {_norm_origin(o) for o in CORS_ORIGINS}
_ADMIN_SET = {_norm_origin(o) for o in ADMIN_ORIGINS}


def audience_of(headers) -> str:
    """Which cookie a request means: the admin dashboard sends `X-Audience: admin`, everything else is the normal app."""
    return "admin" if (headers.get("x-audience") or "").strip().lower() == "admin" else "app"


def csrf_for(token: str) -> str:
    """The CSRF token of a session = HMAC of its token. The browser app receives it in the login / refresh / me answer (a JSON body only an allowed
    origin can read) and sends it back in the X-CSRF-Token header; a forged cross-site request has neither the cookie nor the header."""
    return base64.urlsafe_b64encode(hmac.new(_CSRF_KEY, token.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()


def csrf_ok(method: str, headers, token: str) -> bool:
    """For requests that change something and are authenticated by a cookie: the Origin (when sent) must be an allowed app and X-CSRF-Token must match."""
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return True
    origin = headers.get("origin")
    if origin and _norm_origin(origin) not in _CORS_SET:
        return False
    return hmac.compare_digest(headers.get("x-csrf-token") or "", csrf_for(token))


def check_issue_origin(request: Request, audience: str) -> None:
    """A browser may only be given a session cookie for an app it is really running: admin cookies only to the admin dashboard's origin."""
    origin = _norm_origin(request.headers.get("origin"))
    if audience == "admin":
        if origin not in _ADMIN_SET:
            raise HTTPException(status_code=403, detail="Admin sign-in is only possible from the admin dashboard.")
    elif origin and origin not in _CORS_SET:
        raise HTTPException(status_code=403, detail="Request blocked.")


def _cookie_secure(request: Request) -> bool:
    if COOKIE_SECURE in ("1", "true", "yes"):
        return True
    if COOKIE_SECURE in ("0", "false", "no"):
        return False
    return ratelimit.is_https(request)


def set_session_cookie(response: Response, request: Request, token: str, audience: str) -> None:
    claims = _decode(token)
    response.set_cookie(COOKIE_NAMES[audience], token, max_age=int(claims["exp"] - claims["iat"]), httponly=True, secure=_cookie_secure(request),
                        samesite=COOKIE_SAMESITE, path="/api")


def clear_session_cookie(response: Response, request: Request, audience: str) -> None:
    response.delete_cookie(COOKIE_NAMES[audience], path="/api", httponly=True, secure=_cookie_secure(request), samesite=COOKIE_SAMESITE)


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> User:
    return _authenticate(request, creds)[0]


def _authenticate(request: Request, creds: HTTPAuthorizationCredentials | None) -> tuple[User, dict, str, str]:
    """-> (user, token claims, "bearer" | "cookie", token). A bearer token wins; else the cookie of the audience the request names."""
    audience = audience_of(request.headers)
    if creds is not None:
        token, via = creds.credentials, "bearer"
    else:
        token, via = request.cookies.get(COOKIE_NAMES[audience]), "cookie"
        if not token:
            raise HTTPException(status_code=401, detail="Please log in.")
    user, claims = _user_from_token(token)
    if via == "cookie":
        if audience == "admin":
            if _norm_origin(request.headers.get("origin")) not in _ADMIN_SET:   # a script in the USER app cannot use an admin's cookie
                raise HTTPException(status_code=403, detail="Admin sessions only work from the admin dashboard.")
            if claims.get("scope") != "admin":
                raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        if not csrf_ok(request.method, request.headers, token):
            raise HTTPException(status_code=403, detail="Security check failed. Reload the page and try again.")
    request.state.auth_via, request.state.claims, request.state.token = via, claims, token
    return user, claims, via, token


def _user_from_token(token: str) -> tuple[User, dict]:
    try:
        claims = _decode(token)
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


def renewed_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> tuple[User, str, str, str]:
    """A fresh token for a still valid one, unless the session (since the password was typed) is older than its maximum. -> (user, token, via, audience)"""
    user, claims, via, _ = _authenticate(request, creds)
    start = int(claims.get("ses") or claims.get("iat") or time.time())
    limit = (ADMIN_SESSION_HOURS * 3600) if user.is_admin else (USER_SESSION_DAYS * 86400)
    if time.time() - start > limit:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    audience = claims.get("scope") or ("admin" if user.is_admin else "app")
    return user, make_token(user, start, audience), via, audience


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
