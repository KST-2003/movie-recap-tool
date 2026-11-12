"""Offline: a blur box drawn by hand OVER the source subtitle follows the subtitle blur's time windows (the editor's Blur track);
a box elsewhere stays on for the whole video. Checks the overlap rule (plain, reframed, flipped), the source->output time mapping,
the device plan and the real picture of a render. Run: python test_manual_blur_timed.py"""
import os, subprocess, tempfile
import numpy as np
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db")
import recap_engine as r  # noqa: E402

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

W, H = 360, 640
E = r.EffectOptions
sub = (100, 420, 160, 60)
over, away = (110, 400, 130, 100), (40, 150, 120, 90)
fx = E(captions=False, blur_subtitles=True, subtitle_rect=sub, subtitle_windows=[(1.0, 2.0), (5.0, 6.0)], extra_blur_rects=[over, away])
ok(r.manual_blur_timed(fx, W, H, W, H) == [True, False], "box over the subtitle is timed, box elsewhere is always on")
ok(r.manual_blur_timed(E(blur_subtitles=True, subtitle_rect=sub, subtitle_windows=None, extra_blur_rects=[over]), W, H, W, H) == [False],
   "no windows (subtitle always on) -> box always on")
ok(r.manual_blur_timed(E(blur_subtitles=False, subtitle_rect=sub, subtitle_windows=[(1, 2)], extra_blur_rects=[over]), W, H, W, H) == [False],
   "subtitle blur switched off -> hand-drawn box stays on")
fl = E(blur_subtitles=True, subtitle_rect=(20, 420, 100, 60), subtitle_windows=[(1, 2)], flip_h=True, extra_blur_rects=[(230, 410, 110, 80), (20, 410, 100, 80)])
ok(r.manual_blur_timed(fl, W, H, W, H) == [True, False], "flip: the band is looked up where it is SHOWN (mirrored)")
sq = E(blur_subtitles=True, subtitle_rect=sub, subtitle_windows=[(1, 2)], out_size=(360, 360), fit_mode="blur", extra_blur_rects=[(130, 230, 100, 50), (0, 60, 60, 50)])
got = r.subtitle_rect_in_output(sq, W, H, 360, 360)
ok(abs(got[0] - (78.75 + 100 * 0.5625)) < 1 and abs(got[1] - 420 * 0.5625) < 1, f"fit into 1:1: band at {tuple(round(v) for v in got)}")
ok(r.manual_blur_timed(sq, W, H, 360, 360) == [True, False], "reframed (fit): overlap tested in the output frame")

S = r.Scene
sc = [S(0.0, 2.0, out_len=2.0), S(2.0, 4.0, video_speed=0.8, freeze=0.5, out_len=3.0), S(5.0, 6.0, out_len=1.0)]
m = r._windows_in_output([(1.0, 2.5), (3.5, 4.0), (5.2, 5.6)], sc)
want = [[1.0, 2.625], [3.875, 5.0], [5.2, 5.6]]
ok(len(m) == 3 and all(abs(a - c) < 0.01 and abs(b - d) < 0.01 for (a, b), (c, d) in zip(m, want)), f"source windows -> output times through slow-down, freeze and a skipped part: {[[round(a, 2), round(b, 2)] for a, b in m]}")

src = f"{tmp}/src.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=25:d=8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", src], check=True)
scenes = [S(0.0, 4.0, out_len=4.0), S(4.0, 8.0, out_len=4.0)]
t = 0.0
for s_ in scenes:
    s_.out_start = t; t += s_.out_len

def edges(path, rect, at):
    x, y, w, h = rect
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", path, "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    img = np.frombuffer(raw, dtype=np.uint8).astype(float).reshape(h, w)
    return float(np.abs(np.diff(img, axis=1)).mean() + np.abs(np.diff(img, axis=0)).mean())

out, plain = f"{tmp}/o.mp4", f"{tmp}/p.mp4"
r._render_single(src, [], scenes, fx, out, tmp, "a")
r._render_single(src, [], scenes, E(captions=False), plain, tmp, "b")
top = (over[0], over[1], over[2], 16)   # the part of the hand-drawn box ABOVE the band: only the box blurs it
for at, on in [(1.5, True), (3.5, False), (5.5, True), (7.0, False)]:
    e, p_ = edges(out, top, at), edges(plain, top, at)
    ok((e < p_ * 0.8) == on, f"{at}s: box over the subtitle is {'blurred' if on else 'clear'} ({e:.1f} vs sharp {p_:.1f})")
for at in (1.5, 3.5, 7.0):
    ok(edges(out, away, at) < edges(plain, away, at) * 0.93, f"{at}s: the box elsewhere is blurred all the time")

plan = r.device_plan({"width": W, "height": H, "fps": 25}, scenes, fx, [], 8.0)
ok(plan["manual_timed"] == [True, False] and len(plan["manual_blurs"]) == 2, "device plan says which boxes follow the windows")
print("ALL OK")
