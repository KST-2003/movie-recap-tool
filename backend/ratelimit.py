"""Login / sign-up throttling (security audit 2026-11-19, finding 6). Replaces the old per-IP list in auth.py, which: lived in a plain dict that
was wiped by every restart and never forgot an address; counted successful logins too; shared one bucket between login and sign-up; never looked
at WHICH account was being tried (so one attacker per IP got 1,440 guesses a day at any account, and a botnet unlimited); and counted AFTER the
password check (parallel guesses all passed).

How it works
 * Every login attempt is counted against three budgets BEFORE the password is checked (atomically, under one lock), so 100 parallel guesses
   cannot all slip through:
       per IP (all accounts)          LOGIN_PER_IP       30 / 15 min   credential stuffing from one address
       per account (all addresses)    LOGIN_PER_ACCOUNT  20 / 15 min   a botnet guessing at one account
       per account + IP               LOGIN_PER_PAIR      5 / 15 min   the normal "forgot my password" case, tight
 * A correct password gives the attempt back and clears the per-account counters (`login_succeeded`), so normal users are never slowed down.
   A refused attempt does not burn the other budgets.
 * Sign-up has its own budget (REGISTER_PER_IP 10 / hour); so has the password check of "delete my account" (a stolen session must not be able to
   guess the password there either).
 * Memory only: this server runs ONE API process. The table is bounded (MAX_KEYS, expired keys are dropped first); with several API processes
   each would have its own counters (use Redis then, see the security branch's core/ratelimit.py).
 * The answer is 429 with the old text (it already has Burmese translations) and a `Retry-After` header with the exact seconds.
Trade-off: a per-account budget lets someone lock a victim out for up to 15 minutes by guessing wrong on purpose; the tight per-pair budget and
the bigger per-account one keep that limited, and the owner can always reset the password."""
import math
import os
import threading
import time
from collections import deque

from fastapi import HTTPException

LOGIN_PER_IP = (int(os.getenv("LOGIN_PER_IP", "30")), 900)             # attempts / seconds
LOGIN_PER_ACCOUNT = (int(os.getenv("LOGIN_PER_ACCOUNT", "20")), 900)
LOGIN_PER_PAIR = (int(os.getenv("LOGIN_PER_PAIR", "5")), 900)
REGISTER_PER_IP = (int(os.getenv("REGISTER_PER_IP", "10")), 3600)
PASSWORD_CHECK_PER_USER = (int(os.getenv("PASSWORD_CHECK_PER_USER", "5")), 900)
MAX_PASSWORD_CHARS = 256
MAX_KEYS = int(os.getenv("RATE_LIMIT_MAX_KEYS", "20000"))
MAX_NAME_CHARS = 100          # a login name longer than this is cut for the counters (the real lookup still uses the whole name)

REFUSED_TEXT = "Too many attempts. Try again in a few minutes."

_clock = time.time            # tests replace this to move time forward


class _Store:
    """Sliding window per key. Old keys are dropped, so the table cannot grow without bound."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def take(self, key: str, limit: int, window: int) -> int:
        """Count one attempt. 0 = allowed, else the seconds to wait."""
        now = _clock()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._sweep(now)
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= window:
                q.popleft()
            if len(q) >= limit:
                return max(1, math.ceil(window - (now - q[0])))   # seconds until the oldest counted attempt leaves the window
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

    def size(self) -> int:
        with self._lock:
            return len(self._hits)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def _sweep(self, now: float) -> None:
        longest = max(LOGIN_PER_IP[1], LOGIN_PER_ACCOUNT[1], LOGIN_PER_PAIR[1], REGISTER_PER_IP[1], PASSWORD_CHECK_PER_USER[1])
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] >= longest]:
            del self._hits[k]
        if len(self._hits) > MAX_KEYS:   # still too many live keys (a flood from many addresses): forget the oldest half
            for k in sorted(self._hits, key=lambda k: self._hits[k][-1])[: len(self._hits) // 2]:
                del self._hits[k]


_store = _Store()


def _refuse(wait: int):
    raise HTTPException(status_code=429, detail=REFUSED_TEXT, headers={"Retry-After": str(wait)})


def name_key(name: str) -> str:
    return (name or "").strip().lower()[:MAX_NAME_CHARS]


def login_attempt(ip: str, name: str) -> dict:
    """Count a login attempt against all three budgets BEFORE the password is checked; 429 when any is used up.
    Returns the keys for `login_succeeded`."""
    n = name_key(name)
    keys = {"ip": f"login:ip:{ip}", "account": f"login:acct:{n}", "pair": f"login:pair:{ip}|{n}"}
    taken = []
    for which, (limit, window) in (("ip", LOGIN_PER_IP), ("account", LOGIN_PER_ACCOUNT), ("pair", LOGIN_PER_PAIR)):
        wait = _store.take(keys[which], limit, window)
        if wait:
            for done in taken:   # this attempt is refused outright: do not also burn the other budgets
                _store.refund(keys[done])
            _refuse(wait)
        taken.append(which)
    return keys


def login_succeeded(keys: dict) -> None:
    """The password was right: give the attempt back and clear the account's counters."""
    _store.refund(keys["ip"])
    _store.reset(keys["pair"])
    _store.reset(keys["account"])


def register_attempt(ip: str) -> None:
    wait = _store.take(f"register:ip:{ip}", *REGISTER_PER_IP)
    if wait:
        _refuse(wait)


def password_check_attempt(user_id: int) -> str:
    """For 'delete my account' (needs the password): counts first, returns the key for `password_check_ok`."""
    key = f"pwcheck:user:{user_id}"
    wait = _store.take(key, *PASSWORD_CHECK_PER_USER)
    if wait:
        _refuse(wait)
    return key


def password_check_ok(key: str) -> None:
    _store.reset(key)


def reset_all() -> None:
    """Forget every counter (tests, or the owner after a mistake)."""
    _store.clear()
