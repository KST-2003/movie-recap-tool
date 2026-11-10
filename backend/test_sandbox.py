"""Offline test: ffmpeg / ffprobe / Demucs run without access to the server's secrets (security fix: secret-free media tools).
Linux-only parts (rlimits, /proc protection) are skipped on Windows: run this test inside the Docker image too.
Run: python test_sandbox.py"""
import os
import re
import subprocess
import sys

SECRETS = {"GEMINI_API_KEY": "AIzaSyFAKE-gemini", "SECRET_KEY": "fake-signing-secret", "AZURE_SPEECH_KEY": "fake-azure", "ELEVENLABS_API_KEY": "sk_fake",
           "ANTHROPIC_API_KEY": "sk-ant-fake", "S3_SECRET_KEY": "fake-s3", "S3_ACCESS_KEY": "fake-s3-id", "DATABASE_URL": "postgresql://u:fake-db-pass@db/x",
           "REDIS_URL": "redis://:fake-redis-pass@r:6379", "GCP_SERVICE_ACCOUNT_FILE": "/keys/fake.json", "ADMIN_WEBHOOK_URL": "https://hooks/fake",
           "SOME_NEW_TOKEN": "fake-token"}
os.environ.update(SECRETS)

import sandbox  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def py(code):
    return [sys.executable, "-c", code]


LINUX = os.name == "posix" and os.path.exists("/proc/self")

# ---- 1. the child never sees a secret ----
r = sandbox.run(py("import os,json;print(json.dumps(sorted(os.environ)))"), capture_output=True, text=True, check=True)
import json  # noqa: E402
seen = set(json.loads(r.stdout))
leaked = sorted(set(SECRETS) & seen)
ok(not leaked, f"a media tool gets none of the {len(SECRETS)} secrets in the server's environment" + (f" (LEAKED: {leaked})" if leaked else ""))
ok("PATH" in seen, f"... but still gets PATH and the basics ({len(seen)} variables in all)")
plain = subprocess.run(py("import os;print(os.environ.get('GEMINI_API_KEY'))"), capture_output=True, text=True).stdout.strip()
ok(plain == SECRETS["GEMINI_API_KEY"], "(for contrast: a plain subprocess.run does hand the key to the child)")
r = sandbox.run(py("import os;print(os.environ.get('MY_CHOICE'))"), env={**sandbox.child_env(), "MY_CHOICE": "yes"}, capture_output=True, text=True)
ok(r.stdout.strip() == "yes", "a caller can still pass its own explicit environment")

# ---- 2. it behaves like subprocess.run ----
r = sandbox.run(["ffprobe", "-version"], capture_output=True, text=True)
ok(r.returncode == 0 and "ffprobe version" in r.stdout, "ffprobe runs through the wrapper")
try:
    sandbox.run(py("import sys;sys.exit(3)"), check=True)
    ok(False, "check=True should raise")
except subprocess.CalledProcessError as exc:
    ok(exc.returncode == 3, "check=True raises CalledProcessError with the exit code")
try:
    sandbox.run(py("import time;time.sleep(30)"), timeout=1)
    ok(False, "timeout should raise")
except subprocess.TimeoutExpired:
    ok(True, "timeout= still works")
r = sandbox.run(py("import sys;sys.stdout.write('out');sys.stderr.write('err')"), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
ok(r.stdout == b"out" and r.stderr == b"err", "stdout / stderr pipes work")

# ---- 3. no code path bypasses the wrapper ----
bad = []
for fname in sorted(os.listdir(".")):
    if not fname.endswith(".py") or fname.startswith(("test_", "bench_", "generate_", "compare_")) or fname == "sandbox.py":
        continue
    for n, line in enumerate(open(fname, encoding="utf-8"), 1):
        if re.search(r"subprocess\.(run|Popen|check_output|check_call|call)\(|os\.system\(|os\.popen\(", line):
            bad.append(f"{fname}:{n}: {line.strip()[:90]}")
ok(not bad, "every external program is started through sandbox.run" + ("" if not bad else "\n   " + "\n   ".join(bad)))
ok(sandbox.harden_process.__doc__ and "sandbox.harden_process()" in open("main.py", encoding="utf-8").read() and "sandbox.harden_process()" in open("pipeline.py", encoding="utf-8").read(),
   "the API (main.py) and the worker (pipeline.py) call harden_process at start-up")

# ---- 4. Linux: limits and /proc protection ----
if not LINUX:
    print("SKIP Linux-only checks (rlimits, /proc protection): run this test in the Docker image")
else:
    # 4a. resource limits through prlimit
    ok(sandbox._PRLIMIT is not None, f"prlimit is available ({sandbox._PRLIMIT})")
    code = "import resource;print(resource.getrlimit(resource.RLIMIT_CORE)[0], resource.getrlimit(resource.RLIMIT_CPU)[0], resource.getrlimit(resource.RLIMIT_FSIZE)[0])"
    core, cpu, fsize = map(int, sandbox.run(py(code), capture_output=True, text=True, check=True).stdout.split())
    ok(core == 0 and cpu == sandbox.CPU_SECONDS and fsize == sandbox.MAX_FILE_MB * 1024 * 1024, f"child limits: no core dump, {cpu}s CPU, {fsize // 2**20} MB largest file")
    r = sandbox.run(py("open('/tmp/_sb_big','wb').write(b'x'*(5*1024*1024))"), capture_output=True)
    sandbox.MAX_FILE_MB = 1
    r = sandbox.run(py("open('/tmp/_sb_big','wb').write(b'x'*(5*1024*1024))"), capture_output=True)
    ok(r.returncode != 0, "a child that writes a file bigger than the limit is stopped")
    sandbox.MAX_FILE_MB = 16384
    try:
        os.remove("/tmp/_sb_big")
    except OSError:
        pass

    # 4b. /proc: the old hole, then the fix
    # /proc/<pid>/environ shows the environment a process was STARTED with (what docker's env_file provides), so the demonstration runs in a fresh
    # "server" process that is launched with the secrets, exactly like production.
    driver = r'''
import os, subprocess, sys
sys.path.insert(0, ".")
import sandbox
def snoop(which, runner):
    code = ("import os;d=open('/proc/'+str(os.getppid())+'/" + which + "','rb').read(4000000).decode(errors='replace');"
            "print('LEAK' if 'fake-signing-secret' in d else 'EMPTY')")
    r = runner([sys.executable, "-c", code], capture_output=True, text=True)
    return r.stdout.strip() or (r.stderr.strip().splitlines() or ["?"])[-1]
print("BEFORE_ENVIRON", snoop("environ", subprocess.run))
print("HARDENED", sandbox.harden_process())
print("AFTER_ENVIRON", snoop("environ", sandbox.run))
print("AFTER_MEM", snoop("mem", sandbox.run))
r = sandbox.run(["ffprobe", "-version"], capture_output=True, text=True)
print("STILL_RUNS", r.returncode == 0)
print("SELF_PROC", open("/proc/self/status").read().startswith("Name:"))
'''
    r = subprocess.run([sys.executable, "-c", driver], capture_output=True, text=True, env=dict(os.environ))
    out = dict(line.split(" ", 1) for line in r.stdout.splitlines() if " " in line)
    print(f"NOTE before hardening, a child of the same user reading its parent's /proc/<pid>/environ: {out.get('BEFORE_ENVIRON')}")
    ok(out.get("BEFORE_ENVIRON") == "LEAK", "the hole is real: an unprotected child reads the server's secrets from /proc/<parent>/environ")
    ok(out.get("HARDENED") == "True", "harden_process takes effect (prctl PR_SET_DUMPABLE 0)")
    ok("PermissionError" in out.get("AFTER_ENVIRON", ""), f"after hardening the media tool is refused on /proc/<parent>/environ ({out.get('AFTER_ENVIRON')})")
    ok("PermissionError" in out.get("AFTER_MEM", "") or "OSError" in out.get("AFTER_MEM", ""), f"... and on /proc/<parent>/mem ({out.get('AFTER_MEM')})")
    ok(out.get("STILL_RUNS") == "True", "the hardened process can still start programs")
    ok(out.get("SELF_PROC") == "True", "... and still reads its own /proc/self")

print("ALL OK")
