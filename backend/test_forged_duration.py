"""Offline test (real ffmpeg, fake Gemini / voice): a video whose HEADER length is smaller than its real content is billed AND processed at the
billed length only (security audit 2026-11-19, finding 2). Option C of the owner's decision:
  - header within tolerance of the real length: untouched;
  - somewhat longer content: cut to the billed length, charged for that, the result carries a warning;
  - far longer content (more than 2x the header + 5 s): refused with a clear error, nothing stored or charged;
  - length cannot be read: cut to the billed length anyway;
  - the transcription step is told to read at most the billed length (backstop).
Run: python test_forged_duration.py"""
import hashlib
import os
import struct
import subprocess
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", TTS_PROVIDER="fake", DUB_PROVIDER="gemini", TTS_BULK="0",
                  DATABASE_URL=f"sqlite:///{tmp}/t.db", DEFAULT_DAILY_MINUTES="1000", DEFAULT_MONTHLY_MINUTES="100000", ALLOW_SIGNUP="true",
                  AZURE_SPEECH_KEY="", AZURE_SPEECH_REGION="", GCP_PROJECT_ID="", GCP_SERVICE_ACCOUNT_FILE="")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import common  # noqa: E402
import gemini_dub  # noqa: E402
import main  # noqa: E402


def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c:
        raise SystemExit(1)


def make(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=320x240:r=10:d={seconds}", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "10", "-pix_fmt", "yuv420p", "-c:a", "aac", path], check=True)


def forge_mkv(path, declared_seconds):
    """Rewrite the Matroska Segment Info Duration element so the header claims `declared_seconds` (the packets are untouched)."""
    d = bytearray(open(path, "rb").read())
    i = d.find(b"\x44\x89", 0, 4096)
    size = d[i + 2]
    assert i > 0 and size in (0x84, 0x88), "Duration element not found"
    n = 4 if size == 0x84 else 8
    d[i + 3:i + 3 + n] = struct.pack(">f" if n == 4 else ">d", declared_seconds * 1000.0)   # TimecodeScale 1 ms
    open(path, "wb").write(d)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fresh(name, real, declared=None):
    p = f"{tmp}/{name}"
    make(p, real)
    if declared is not None:
        forge_mkv(p, declared)
    return p


# ---------------------------------------------------------------- 1. measuring the real length
honest = fresh("honest.mp4", 20)
ok(abs(common.real_media_duration(honest) - 20) < 0.6, "real length of an honest 20 s mp4 = ~20 s")
liar = fresh("liar.mkv", 30, declared=1)
ok(abs(common.media_duration(liar) - 1.0) < 0.05, "PRECONDITION: the header of the forged mkv says 1.0 s (what billing used to believe)")
ok(abs(common.real_media_duration(liar) - 30) < 0.6, "the packet scan finds the real ~30 s")
junk = f"{tmp}/junk.bin"; open(junk, "wb").write(os.urandom(5000))
ok(common.real_media_duration(junk) is None, "a file that is not media: None")
ok(common.real_media_duration(honest, timeout=0.0) is None, "no time left for the scan: None (never blocks)")

# ---------------------------------------------------------------- 2. the decision, branch by branch
p = fresh("ok.mp4", 20); before = sha(p)
got = main.enforce_real_length(p, common.media_duration(p))
ok(abs(got[0] - 20) < 0.3 and got[1] is None and sha(p) == before, "honest file: billed as it is, file untouched, no note")

p = fresh("tol.mkv", 30, declared=29)   # 30 s <= 29 x 1.05 + 2
before = sha(p)
got = main.enforce_real_length(p, common.media_duration(p))
ok(abs(got[0] - 29) < 0.1 and got[1] is None and sha(p) == before, "a header only 1 s short (inside the 5 % + 2 s tolerance): left alone")

p = fresh("moderate.mkv", 30, declared=20)   # 30 > 20 x 1.05 + 2 and <= 20 x 2 + 5
got = main.enforce_real_length(p, common.media_duration(p))
ok(abs(got[0] - 20) < 1.2 and got[1] and got[1]["declared"] == 20.0 and abs(got[1]["real"] - 30) < 0.6, f"header 20 s / content 30 s: billed ~20 s, note kept {got[1]}")
ok(abs(common.real_media_duration(p) - got[0]) < 1.0 and abs(common.media_duration(p) - got[0]) < 0.3, "... and the stored file was cut: its real length now matches what is billed")

p = fresh("huge.mkv", 30, declared=1)   # 30 > 1 x 2 + 5
before = sha(p)
try:
    main.enforce_real_length(p, common.media_duration(p)); refused = None
except HTTPException as exc:
    refused = exc
ok(refused is not None and refused.status_code == 400 and "looks damaged" in refused.detail, "header 1 s / content 30 s: refused (400, 'looks damaged')")
ok(sha(p) == before, "... the refused file was not modified")

p = fresh("unreadable.mp4", 20); orig = main.real_media_duration
main.real_media_duration = lambda path, **k: None   # the scan failed or ran out of time
got = main.enforce_real_length(p, common.media_duration(p))
main.real_media_duration = orig
ok(abs(got[0] - 20) < 1.2 and got[1] is None, "length unreadable: the file is still cut to the billed length (no note, nothing to say)")

# ---------------------------------------------------------------- 3. backstop: the transcription step is told how much it may read
cmds = []
class Stop(Exception):
    pass
def capture(cmd, *a, **k):
    cmds.append(cmd); raise Stop()
real_run = gemini_dub._run; gemini_dub._run = capture
for kwargs in ({"max_seconds": 21.5}, {}):
    cmds.clear()
    try:
        gemini_dub.dub(honest, "my", **kwargs)
    except Stop:
        pass
    cmd = cmds[0]
    if kwargs:
        ok("-t" in cmd and cmd[cmd.index("-t") + 1] == "21.500" and cmd.index("-t") < cmd.index("-i"), "dub(): audio extraction has -t 21.5 as an INPUT option")
    else:
        ok("-t" not in cmd, "dub() without max_seconds: unchanged command")
gemini_dub._run = real_run

# ---------------------------------------------------------------- 4. the whole upload path through the API
TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
seen = {}
def fake_dub(path, target, **kw):
    seen["length"] = common.media_duration(path)
    seen["max"] = kw.get("max_seconds")
    segs = [{"start": i * 4.0, "end": i * 4.0 + 3.6, "source_text": "x", "translated_text": TEXT} for i in range(max(1, int(seen["length"] // 4)))]
    return "zh", gemini_dub.finish_segments(segs, kw.get("scene_cuts") or [])
gemini_dub.dub = fake_dub
c = TestClient(main.app)
tok = c.post("/api/auth/register", json={"email": "t@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": f"Bearer {tok}"}
left = lambda: c.get("/api/auth/me", headers=H).json()["remaining_seconds"]


def upload(path):
    with open(path, "rb") as f:
        return c.post("/api/jobs", headers=H, files={"video_file": (os.path.basename(path), f, "video/mp4")},
                      data={"voice_type": "su", "fit_translation": "false", "resolution": "720"})


def finish(job_id):
    while True:
        j = c.get(f"/api/jobs/{job_id}", headers=H).json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(1)


# 4a. honest upload: no warning, billed for its length
b0 = left(); r = upload(fresh("api_ok.mp4", 16)); j = finish(r.json()["job_id"])
ok(r.status_code == 200 and j["status"] == "done", f"honest 16 s upload finishes ({r.status_code} {j.get('error')})")
ok(not any("says it is" in w for w in (j["result"].get("warnings") or [])), "... no length warning")
ok(abs((b0 - left()) - 16) < 1.5, f"... billed ~16 s ({b0 - left():.1f})")

# 4b. moderate mismatch: billed + processed 20 s, warning on the result
uploads_before = set(os.listdir(f"{tmp}/up"))
b0 = left(); r = upload(fresh("api_mod.mkv", 30, declared=20)); j = finish(r.json()["job_id"])
ok(r.status_code == 200 and j["status"] == "done", f"mkv with header 20 s / content 30 s is accepted and finishes ({r.status_code} {j.get('error')})")
ok(abs((b0 - left()) - 20) < 1.5, f"... billed ~20 s, not 30 ({b0 - left():.1f})")
ok(abs(seen["length"] - 20) < 1.2, f"... the transcription step got a ~20 s file ({seen['length']:.1f} s)")
ok(seen["max"] is not None and abs(seen["max"] - (seen["length"] + 2.0)) < 1.5, f"... and was told max_seconds={seen['max']:.1f} (billed length + 2)")
warns = j["result"].get("warnings") or []
ok(any(w == "This video file says it is 0:20 long but contains about 0:30, so only the first 0:20 were used." for w in warns), f"... the result says so: {warns}")
ok(abs(float(j["result"]["project"]["source_duration"]) - seen["length"]) < 0.5, "... the project (editor) length is the billed length")

# 4c. huge mismatch: refused, nothing billed, nothing left on disk, no job
b0 = left(); stored = set(os.listdir(f"{tmp}/up"))
r = upload(fresh("api_huge.mkv", 30, declared=1))
ok(r.status_code == 400 and "looks damaged" in r.json()["detail"], f"header 1 s / content 30 s is refused with a clear error ({r.status_code} {r.json().get('detail')})")
ok(left() == b0, "... nothing was charged")
ok(set(os.listdir(f"{tmp}/up")) == stored, "... nothing was left in the upload folder")
ok(len(c.get("/api/jobs", headers=H).json()["items"]) == 2, "... no job was created (still the 2 earlier ones)")

# 4d. a normal broken file is still refused the old way
bad = f"{tmp}/bad.mp4"; open(bad, "wb").write(b"not a video")
ok(upload(bad).status_code == 400, "a broken file is still refused (400)")
print("ALL OK")
