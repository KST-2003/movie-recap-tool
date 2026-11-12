"""Offline test of the time-left estimate (eta.py) and of the job view carrying it. Run: python test_eta.py"""
import os
import tempfile
import time
from datetime import datetime, timezone

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db", ALLOW_SIGNUP="true")
import eta  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


T0 = 1_000_000.0
# no history: a 600 s server-rendered video, 60 s in, still translating (progress 10 reached at 50 s)
e = eta.estimate({}, 600, T0, 10, [{"progress": 3, "at": iso(T0 + 5)}, {"progress": 10, "at": iso(T0 + 50)}], [], T0 + 60)
ok(e and 300 < e["eta_seconds"] < 600 and not e["over"], f"no history, early: {e}")
# the same video at the start of the render after 200 s: its own speed says total ~333 s
st = [{"progress": 75, "at": iso(T0 + 200)}]
e = eta.estimate({}, 600, T0, 75, st, [], T0 + 200)
ok(e and 100 < e["eta_seconds"] < 220, f"render just started: {e}")
e2 = eta.estimate({}, 600, T0, 75, st, [], T0 + 260)
ok(e2["eta_seconds"] == e["eta_seconds"] - 60, f"60 s later, same progress: 60 s less ({e2})")
e3 = eta.estimate({}, 600, T0, 75, st, [], T0 + 900)
ok(e3["over"] and e3["eta_seconds"] == 0, f"far past the estimate: flagged as over, not a wrong number ({e3})")
# render progress moves: 87 (half the render) reached at 280 s
e = eta.estimate({}, 600, T0, 87, st + [{"progress": 87, "at": iso(T0 + 280)}], [], T0 + 280)
ok(e and 40 < e["eta_seconds"] < 160, f"half way through the render: {e}")

# history: device-render videos take 0.3 x their length here and the sound step starts at 90% of the run
hist = [{"kind": "device", "seconds": 600, "run_seconds": 180, "started_at": T0, "stages": [{"progress": 75, "at": iso(T0 + 162)}]},
        {"kind": "device", "seconds": 300, "run_seconds": 90, "started_at": T0, "stages": [{"progress": 75, "at": iso(T0 + 81)}]},
        {"kind": "render", "seconds": 600, "run_seconds": 900, "started_at": T0, "stages": []}]
k = eta.learn(hist, "device")
ok(abs(k["ratio"] - 0.3) < 0.01 and abs(k["render_share"] - 0.9) < 0.01, f"learned from history: {k}")
e = eta.estimate({"device_render": True}, 600, T0, 10, [{"progress": 10, "at": iso(T0 + 30)}], hist, T0 + 30)
ok(e and 120 < e["eta_seconds"] < 190, f"history is used for the same kind only: {e}")
ok(eta.kind_of({"edit": {"segments": []}}) == "edit" and eta.kind_of({"output": "subtitles"}) == "subtitles" and eta.kind_of({}) == "render", "kinds")
ok(eta.estimate({}, 600, None, 10, [], [], T0) is None, "not started: no estimate")
ok(eta.estimate({"edit": {"segments": []}}, 0, T0, 1, [], [], T0 + 2) is None, "an edit with no history and no progress yet: no estimate")
ok(abs(eta.share_at(100) - 1) < 1e-9 and eta.share_at(75, 0.9) == 0.9 and eta.share_at(10) < eta.share_at(60), "curve")

# the API: a running job's view carries eta_seconds, a finished one does not, and the admin-only fields stay hidden
import main  # noqa: E402
from db import Job, Session, User  # noqa: E402

with Session() as s:
    u = User(email="e@example.com", password_hash="x"); s.add(u); s.commit()
    now = time.time()
    j = Job(id="run1", user_id=u.id, status="running", stage="Rendering video", progress=75, params={}, charged_seconds=300,
            data={"started_at": now - 120, "stages": [{"stage": "Rendering video", "progress": 75, "at": iso(now - 20)}]})
    d = Job(id="done1", user_id=u.id, status="done", stage="Done", progress=100, params={}, charged_seconds=300, data={"run_seconds": 200})
    s.add_all([j, d]); s.commit()
    v, vd = main._job_view(j), main._job_view(d)
ok(isinstance(v.get("eta_seconds"), int) and 5 < v["eta_seconds"] < 400 and v["eta_over"] is False, f"running job view: eta_seconds={v.get('eta_seconds')}")
ok("eta_seconds" not in vd and "stages" not in v and "started_at" not in v, "finished job has no estimate; stage history stays admin-only")
print("ALL OK")
