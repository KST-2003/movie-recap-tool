"""Decisive test of the Postgres-specific half of the admission fix (db.lock_admission / pg_advisory_xact_lock).

Every other admission test (test_admission_race.py) runs on SQLite, where serialisation comes from capacity.lock, a
plain Python threading.Lock -- which only works within ONE process. In production there are several API/worker
PROCESSES sharing one Postgres database, and capacity.lock in process A does nothing to stop process B. The thing
that is actually supposed to stop them stepping on each other there is `pg_advisory_xact_lock` in db.lock_admission.
This test is the only one that can prove that: it starts a REAL Postgres container and TWO SEPARATE OS PROCESSES
(not threads), gives one user a tight daily-minute budget, and fires uploads at both processes at once.

  PART A (the real code, unmodified): with the Postgres lock active, the budget must hold across both processes.
  PART B (control): the SAME two-process setup, but with db.lock_admission replaced by a no-op AND the window
  between the limit check and the commit deliberately widened (exactly the technique test_admission_race.py uses on
  SQLite) -- this must show the race (budget exceeded), proving PART A passing is the lock's doing, not luck.

Needs Docker (pulls postgres:16-alpine) and no proxy blocking 127.0.0.1. Cleans up the container/network/volume it
creates. Run: python test_postgres_admission_lock.py
"""
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
CONTAINER = f"pgtest-{secrets.token_hex(4)}"
PG_PASSWORD = secrets.token_hex(8)
SECRET_KEY = secrets.token_hex(32)
VIDEO_SECONDS = 40            # real ffprobe duration of the test upload
DAILY_MINUTES = 1              # 60 s budget: two 40 s uploads (80 s) must never BOTH be admitted
results = []


def ok(cond, msg):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + msg, flush=True)


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if not shutil.which("docker"):
    print("SKIP: Docker is not available, cannot start a real Postgres. Nothing was changed.")
    sys.exit(0)

try:
    subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
except Exception:
    print("SKIP: the Docker daemon is not running. Nothing was changed.")
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix="pgtest-")
PG_PORT = free_port()
PORT_A = free_port()
PORT_B = free_port()
procs = []


def cleanup():
    for p in procs:
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)


CHILD_SERVER = textwrap.dedent('''
    import os, sys, time
    sys.path.insert(0, %r)
    os.chdir(%r)
    import main
    if os.environ.get("DISABLE_PG_LOCK") == "1":
        main.lock_admission = lambda s: None   # the fix under test, removed -- this is the CONTROL only
        import capacity
        _real = capacity.decide
        def _slow(*a, **kw):
            time.sleep(0.3)      # widen the check-then-commit window (same technique test_admission_race.py uses)
            return _real(*a, **kw)
        capacity.decide = _slow
    import uvicorn
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ["PORT"]), log_level="warning")
''' % (ROOT, ROOT))
child_path = os.path.join(tmp, "child_server.py")
open(child_path, "w").write(CHILD_SERVER)


def start_postgres():
    print(f"starting postgres:16-alpine as {CONTAINER} on 127.0.0.1:{PG_PORT} ...", flush=True)
    r = subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
                       "-e", "POSTGRES_DB=recap", "-p", f"127.0.0.1:{PG_PORT}:5432", "postgres:16-alpine"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit("could not start postgres container")
    for _ in range(60):
        chk = subprocess.run(["docker", "exec", CONTAINER, "pg_isready", "-U", "postgres"], capture_output=True)
        if chk.returncode == 0:
            return
        time.sleep(1)
    raise SystemExit("postgres never became ready")


def child_env(port, disable_lock, database_url):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP")}
    env.update(PORT=str(port), DATABASE_URL=database_url, SECRET_KEY=SECRET_KEY, DISABLE_PG_LOCK=("1" if disable_lock else ""),
              AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="", ADMIN_WEBHOOK_URL="",
              DATA_DIR=os.path.join(tmp, f"data-{port}"), UPLOAD_DIR=os.path.join(tmp, f"up-{port}"), OUTPUT_DIR=os.path.join(tmp, f"out-{port}"),
              TTS_PROVIDER="fake", GEMINI_API_KEY="x", GLOBAL_DAILY_MINUTES="0", SIGNUP_DAILY_MINUTES=str(DAILY_MINUTES),
              SIGNUP_MONTHLY_MINUTES="1000", SIGNUP_MAX_PER_DAY="0", MAX_ACTIVE_JOBS_PER_USER="1000", MAX_VIDEO_MINUTES="600",
              PASSWORD_SCRYPT_LOG2_N="10", PASSWORD_SCRYPT_P="1", PYTHONUTF8="1")
    return env


def wait_healthy(port):
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit(f"child server on port {port} never came up")


def start_pair(database_url, disable_lock):
    # Started one at a time on purpose: Base.metadata.create_all races with ITSELF if two fresh processes hit a
    # brand-new database at the same instant (both try CREATE TABLE -> UniqueViolation on the sequence). That is a
    # startup-order artifact of this harness, not the admission lock under test, so avoid it by not racing it.
    a = subprocess.Popen([PY, child_path], env={**child_env(PORT_A, disable_lock, database_url)})
    procs.append(a)
    wait_healthy(PORT_A)
    b = subprocess.Popen([PY, child_path], env={**child_env(PORT_B, disable_lock, database_url)})
    procs.append(b)
    wait_healthy(PORT_B)
    return f"http://127.0.0.1:{PORT_A}", f"http://127.0.0.1:{PORT_B}"


def make_user(base, label):
    email, pw = f"{label}-{secrets.token_hex(4)}@pgtest.local", "Password123!"
    r = requests.post(f"{base}/api/auth/register", json={"email": email, "password": pw})
    if r.status_code != 200:
        raise SystemExit(f"signup failed: {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def burst(base_a, base_b, headers, video_bytes, n=10):
    def upload(i):
        base = base_a if i % 2 == 0 else base_b
        r = requests.post(f"{base}/api/jobs", headers=headers, files={"video_file": (f"v{i}.mp4", video_bytes, "video/mp4")},
                          data={"output": "subtitles"}, timeout=30)
        return r.status_code
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(upload, range(n)))


video_path = os.path.join(tmp, "test.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=s=64x64:d={VIDEO_SECONDS}:r=5", "-c:v", "mpeg4", video_path], check=True)
video_bytes = open(video_path, "rb").read()
print(f"test video: {VIDEO_SECONDS}s, {len(video_bytes)} bytes")
max_fit = (DAILY_MINUTES * 60) // VIDEO_SECONDS
print(f"budget {DAILY_MINUTES * 60}s / video {VIDEO_SECONDS}s -> at most {max_fit} of these may EVER be admitted for one user in one day")

try:
    start_postgres()
    database_url = f"postgresql+psycopg://postgres:{PG_PASSWORD}@127.0.0.1:{PG_PORT}/recap"

    print("\n=== PART A: the real fix, two separate processes, Postgres advisory lock ACTIVE ===")
    base_a, base_b = start_pair(database_url, disable_lock=False)
    headers = make_user(base_a, "alice")
    codes = burst(base_a, base_b, headers, video_bytes, n=10)
    admitted = codes.count(200)
    print(f"codes: {codes}")
    ok(admitted == max_fit, f"10 parallel 40s uploads across TWO PROCESSES, 60s budget -> {admitted} admitted (must be exactly {max_fit})")
    for p in procs:
        p.terminate()
        p.wait(timeout=5)
    procs.clear()

    print("\n=== PART B (control): SAME two processes, Postgres lock DISABLED + window widened ===")
    base_a, base_b = start_pair(database_url, disable_lock=True)
    headers = make_user(base_a, "bob")
    codes = burst(base_a, base_b, headers, video_bytes, n=10)
    admitted = codes.count(200)
    print(f"codes: {codes}")
    ok(admitted > max_fit, f"SAME test, lock disabled -> {admitted} admitted (must be MORE than {max_fit}, proving the lock in Part A was load-bearing, not luck)")
finally:
    cleanup()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{sum(results)} of {len(results)} checks passed")
sys.exit(0 if all(results) else 1)
