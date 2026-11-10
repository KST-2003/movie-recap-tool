"""Run ffmpeg / ffprobe / Demucs (programs that decode files UPLOADED BY STRANGERS) with as little power as possible.

The API and worker processes hold every secret (Gemini / Azure / ElevenLabs keys, database and Redis URLs, S3 keys). A bug in a decoder could give a
stranger code execution inside the child process, so the child must not be able to reach those secrets:
 1. `child_env()`: the child gets a short allow-list of environment variables (PATH, temp dirs, locale ...), never the keys. Nothing is inherited.
 2. `harden_process()` (Linux): the API / worker process marks itself NON-DUMPABLE (prctl PR_SET_DUMPABLE 0). Then /proc/<pid>/environ, /proc/<pid>/mem
    and ptrace of that process are refused to every other process of the same user, including its own ffmpeg children. Without this a child of the
    same user can simply read its parent's /proc/<ppid>/environ (the initial environment, e.g. everything docker's env_file provided).
 3. `run()` puts `prlimit` in front of the command when it exists (Linux): no core dumps, a CPU-time ceiling and a largest-file ceiling, so a decoder
    bomb cannot spin for ever or fill the disk with one file. (No preexec_fn: it is unsafe in a process full of threads.)
Memory limits belong to the container (`mem_limit` in docker-compose); the optional SANDBOX_MEMORY_MB adds an address-space ceiling.
This is not a full sandbox (no seccomp / namespaces: those need privileges a plain container does not give). The compose file adds the rest
(read-only root file system, no capabilities, no-new-privileges). Keep this module free of heavy imports."""
import os
import shutil
import subprocess

# Everything else is dropped. Add a name here only if a tool really needs it, never a key or a URL with a password.
_ALLOWED_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
                "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CACHE_HOME", "XDG_DATA_HOME", "TORCH_HOME", "OMP_NUM_THREADS",
                "FONTCONFIG_PATH", "FONTCONFIG_FILE", "TZ")

CPU_SECONDS = int(os.getenv("SANDBOX_CPU_SECONDS", "3600"))        # CPU time of one ffmpeg / Demucs run
MAX_FILE_MB = int(os.getenv("SANDBOX_MAX_FILE_MB", "16384"))       # largest file one run may write
MEMORY_MB = int(os.getenv("SANDBOX_MEMORY_MB", "0"))                # address-space ceiling, 0 = off (torch / ffmpeg map a lot of virtual memory)
_PRLIMIT = shutil.which("prlimit") if os.name == "posix" else None


def child_env() -> dict:
    """The environment a media tool gets: the allow-list above, nothing else."""
    return {k: os.environ[k] for k in _ALLOWED_ENV if k in os.environ}


def _wrap(cmd):
    if not _PRLIMIT or not isinstance(cmd, (list, tuple)):
        return cmd
    limits = ["--core=0", f"--cpu={CPU_SECONDS}", f"--fsize={MAX_FILE_MB * 1024 * 1024}"]
    if MEMORY_MB:
        limits.append(f"--as={MEMORY_MB * 1024 * 1024}")
    return [_PRLIMIT, *limits, "--", *cmd]


def run(cmd, **kwargs):
    """subprocess.run for media tools: scrubbed environment, resource limits. Same arguments and results as subprocess.run."""
    kwargs.setdefault("env", child_env())
    return subprocess.run(_wrap(cmd), **kwargs)


def harden_process() -> bool:
    """Make THIS process non-dumpable (Linux). Call once at start-up in the API and in every worker. Returns True when it took effect."""
    if os.name != "posix" or not os.path.exists("/proc/self"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_DUMPABLE = 4
        return libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except Exception:
        return False
