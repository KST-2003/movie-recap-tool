"""Offline test of the picture retiming chain (`recap_engine._retime_chain`): every output moment must show the right SOURCE moment
through normal scenes, a slowed scene, a freeze, a skipped part of the source and a freeze at the very end. The source picture's
brightness encodes its time (grey level = 20 + 20 x seconds), so the source time of any output frame can be read back.
Run: python test_retime.py"""
import os
import subprocess
import tempfile

import numpy as np

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db")
import recap_engine as r  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


W, H, FPS, LEN = 160, 284, 25, 8
src = f"{tmp}/src.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={LEN}",
                "-vf", "geq=lum='20+20*T':cb=128:cr=128", "-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", "yuv420p", src], check=True)

S = r.Scene
scenes = [S(0.0, 2.0, out_len=2.0),                                    # as it is
          S(2.0, 4.0, video_speed=0.8, freeze=0.5, out_len=3.0),       # slowed to 2.5 s, then held 0.5 s
          S(5.0, 6.0, out_len=1.0),                                    # source 4-5 s is skipped
          S(6.0, 7.0, freeze=1.0, out_len=2.0)]                        # freeze at the very end
t = 0.0
for sc in scenes:
    sc.out_start = t
    t += sc.out_len
total = t
out = f"{tmp}/out.mp4"
r._render_single(src, [], scenes, r.EffectOptions(captions=False), out, tmp, "t")

dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
ok(abs(dur - total) < 0.08, f"output length {dur:.2f}s = planned {total:.2f}s")
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-vf", "scale=16:16", "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"], capture_output=True).stdout
frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 384)[:, :256].mean(axis=1)   # the Y plane as stored (no range conversion)
ok(abs(len(frames) - total * FPS) <= 2, f"{len(frames)} frames for {total * FPS:.0f} planned")


def src_time(out_t):
    return (frames[min(int(round(out_t * FPS)), len(frames) - 1)] - 20) / 20


TOL = 0.12   # 2 frames + encoder rounding
for out_t, want, what in [(1.0, 1.0, "normal scene"), (3.25, 3.0, "slowed scene (0.8x) is at its middle"), (4.4, 3.92, "end of the slowed scene"),
                          (4.85, 3.96, "freeze holds the scene's last frame"), (5.5, 5.5, "after a skipped part of the source"),
                          (6.5, 6.5, "last scene"), (7.8, 6.96, "freeze at the very end")]:
    got = src_time(out_t)
    ok(abs(got - want) < TOL, f"output {out_t:.2f}s shows source {got:.2f}s (want {want:.2f}s): {what}")
ok(not any(4.1 < (v - 20) / 20 < 4.9 for v in frames), "no frame from the skipped part (source 4-5 s) is shown")
print("ALL OK")
