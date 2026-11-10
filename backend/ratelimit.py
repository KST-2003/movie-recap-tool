"""Rate limits for login / signup, and the real client address behind a reverse proxy.

Replaces the old per-IP in-memory counter in auth.py, which: counted successful logins too, shared one bucket between login and signup,
was per process (2 uvicorn workers = double the allowance), never forgot an address, saw only the proxy's address behind a reverse proxy
(everyone locked out together), and let parallel guesses all pass because it counted AFTER the password check.

How it works
 * `take(key, limit, window)` counts the attempt FIRST (atomically) and returns 0 if allowed, else the seconds to wait. Counting before
   the password check means 100 parallel guesses cannot all slip through. A successful login gives its hit back (`refund` / `reset`).
 * Login uses three budgets: per IP (credential stuffing across accounts), per account from any IP (distributed guessing at one
   account), per IP + account (the normal "forgot my password" case, tight).
 * Storage: Redis when REDIS_URL is set (shared by all API processes), else memory with eviction. If Redis fails the limiter falls back to
   memory for that call (never to "no limit", never to a 500).
 * `client_ip` only believes X-Forwarded-For when the direct peer is in TRUSTED_PROXIES (comma separated IPs / CIDRs). Empty (default) =
   ignore the header, so it cannot be spoofed. Behind nginx/Caddy/Docker set TRUSTED_PROXIES to the proxy's address or network."""
import hashlib
import ipaddress
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from config import REDIS_URL

LOGIN_PER_IP = (int(os.getenv("LOGIN_PER_IP", "30")), 900)          # attempts / seconds, all accounts, one address
LOGIN_PER_ACCOUNT = (int(os.getenv("LOGIN_PER_ACCOUNT", "20")), 900)  # one account, all addresses
LOGIN_PER_PAIR = (int(os.getenv("LOGIN_PER_PAIR", "5")), 900)       # one account from one address
REGISTER_PER_IP = (int(os.getenv("REGISTER_PER_IP", "10")), 3600)
MAX_PASSWORD_CHARS = 256


# ---------------------------------------------------------------- storage

class MemoryStore:
    """Sliding window per key. Old keys are dropped, so the table cannot grow without bound."""

    def __init__(self, max_keys: int = 20000):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def take(self, key: str, limit: int, window: int) -> int:
        now = time.time()
        with self._lock:
            if len(self._hits) > self._max_keys:
                self._sweep(now, window)
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return max(1, int(window - (now - q[0])) + 1)
            q.append(now)
            return 0

    def refund(self, key: str) -> None:
        with self._lock:
            q = self._hits.get(key)
            if q:
                q.pop()
                if not q:
                    del self._hits[key]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _sweep(self, now: float, window: int) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= max(window, 3600)]:
            del self._hits[k]
        if len(self._hits) > self._max_keys:   # still too many live keys: forget the oldest half
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: len(self._hits) // 2]:
                del self._hits[k]


class RedisStore:
    """Fixed window counters (INCR + EXPIRE): one atomic round trip, shared by every API process."""

    def __init__(self, url: str):
        from redis import Redis
        self._r = Redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)

    def _k(self, key: str) -> str:
        return "rl:" + hashlib.sha256(key.encode()).hexdigest()[:40]

    def take(self, key: str, limit: int, window: int) -> int:
        k = self._k(key)
        pipe = self._r.pipeline()   # one MULTI transaction: the key always gets its expiry, even if this process dies right after
        pipe.set(k, 0, ex=window, nx=True)
        pipe.incr(k)
        pipe.ttl(k)
        _, count, ttl = pipe.execute()
        if count > limit:
            self._r.decr(k)   # a refused attempt does not extend the lock
            return max(1, int(ttl))
        return 0

    def refund(self, key: str) -> None:
        k = self._k(key)
        if int(self._r.get(k) or 0) > 0:
            self._r.decr(k)

    def reset(self, key: str) -> None:
        self._r.delete(self._k(key))


_memory = MemoryStore()
_redis = None
_redis_failed_at = 0.0


def _store(use_redis: bool = True):
    global _redis, _redis_failed_at
    if not (REDIS_URL and use_redis) or time.time() - _redis_failed_at < 30:
        return _memory
    if _redis is None:
        try:
            _redis = RedisStore(REDIS_URL)
        except Exception:
            _redis_failed_at = time.time()
            return _memory
    return _redis


def _call(method: str, *args):
    """Run a store method on Redis; on any Redis problem use memory (and stop trying Redis for 30 s)."""
    global _redis_failed_at
    store = _store()
    try:
        return getattr(store, method)(*args)
    except Exception as exc:
        if store is _memory:
            raise
        _redis_failed_at = time.time()
        print(f"[ratelimit] Redis unavailable, using memory: {exc}", flush=True)
        return getattr(_memory, method)(*args)


def take(key: str, limit: int, window: int) -> int:
    return _call("take", key, limit, window)


def refund(key: str) -> None:
    _call("refund", key)


def reset(key: str) -> None:
    _call("reset", key)


# ---------------------------------------------------------------- who is calling

def _networks() -> list:
    out = []
    for item in os.getenv("TRUSTED_PROXIES", "").split(","):
        item = item.strip()
        if item:
            try:
                out.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                print(f"[ratelimit] ignoring bad TRUSTED_PROXIES entry: {item!r}", flush=True)
    return out


def client_ip(request: Request) -> str:
    """The caller's address. X-Forwarded-For is used only when the direct peer is a trusted proxy; then the right-most entry that is
    NOT a trusted proxy is the client (entries further left can be written by the client itself)."""
    peer = request.client.host if request.client else "?"
    trusted = _networks()
    if not trusted:
        return peer

    def is_trusted(addr: str) -> bool:
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        return any(ip in net for net in trusted)

    if not is_trusted(peer):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not is_trusted(hop):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                return peer   # garbage header: fall back to the proxy's address rather than trust it
    return peer


# ---------------------------------------------------------------- the checks used by the API

def _refuse(wait: int):
    minutes = max(1, (wait + 59) // 60)
    raise HTTPException(status_code=429, detail=f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.",
                        headers={"Retry-After": str(wait)})


def check_password_length(password: str) -> None:
    if len(password) > MAX_PASSWORD_CHARS:
        raise HTTPException(status_code=400, detail=f"Password can be at most {MAX_PASSWORD_CHARS} characters.")


def login_attempt(request: Request, email: str) -> dict:
    """Count a login attempt against all three budgets BEFORE the password is checked. Returns the keys for `login_succeeded`."""
    ip = client_ip(request)
    keys = {"ip": f"login:ip:{ip}", "account": f"login:acct:{email}", "pair": f"login:pair:{ip}|{email}"}
    taken = []
    for name, (limit, window) in (("ip", LOGIN_PER_IP), ("account", LOGIN_PER_ACCOUNT), ("pair", LOGIN_PER_PAIR)):
        wait = take(keys[name], limit, window)
        if wait:
            for done in taken:   # this attempt is refused outright: do not also burn the other budgets
                refund(keys[done])
            _refuse(wait)
        taken.append(name)
    return keys


def login_succeeded(keys: dict) -> None:
    """A correct password gives the attempt back and clears the per-account counters, so normal users are never slowed down."""
    refund(keys["ip"])
    reset(keys["pair"])
    reset(keys["account"])


def register_attempt(request: Request) -> None:
    wait = take(f"register:ip:{client_ip(request)}", *REGISTER_PER_IP)
    if wait:
        _refuse(wait)
