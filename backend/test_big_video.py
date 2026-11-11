"""Offline test: a phone clip (4K, stored landscape + "rotate 90" flag): displayed size, 1080p cap in Original format, fast subtitle step.
Run: python test_big_video.py"""
import os
import subprocess
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db")
import common  # noqa: E402
import pipeline  # noqa: E402
import recap_engine as r  # noqa: E402
import subtitle_detect as sd  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


raw, rot = f"{tmp}/raw.mp4", f"{tmp}/rot.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=3840x2160:r=30:d=7", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-pix_fmt", "yuv420p", raw], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "90", "-i", raw, "-c", "copy", rot], check=True)

ok(common.display_size(raw) == (3840, 2160), "no rotation flag: stored size")
ok(common.display_size(rot) == (2160, 3840), "rotate 90 flag: displayed size is portrait")
info = r.probe_video(rot)
ok((info["width"], info["height"]) == (2160, 3840), "probe_video uses the displayed size")
ok(pipeline._out_size("original", info) == (1080, 1920), "Original format: a 4K clip is rendered at 1080p (same shape)")
ok(pipeline._out_size("original", {"width": 720, "height": 1280}) is None and pipeline._out_size("original", {"width": 1080, "height": 1920}) is None, "Original format: small clips are untouched")
ok(pipeline._out_size("original", info, 720) == (720, 1280) and pipeline._out_size("9:16", info, 720) == (720, 1280), "720p: short side 720")
ok(pipeline._out_size("original", {"width": 1080, "height": 1920}, 720) == (720, 1280), "720p: a 1080p clip is scaled down")
ok(pipeline._out_size("original", {"width": 540, "height": 960}, 720) is None, "720p: never scaled up")
ok(pipeline._out_size("16:9", info) == (1920, 1080), "other formats still cap at 1080 short side")

src = sd._Frames(rot, 7.0, 14)
f0 = src.get(0)
ok(src.fast and f0 is not None and max(f0.shape[:2]) == 960 and f0.shape[0] > f0.shape[1], "keyframe reader: long side 960, portrait (the displayed shape)")
# early stop: no text anywhere -> only EARLY_STOP frames are read by the text detector
calls = []
real = sd._engine()
sd._ocr = lambda img, *a, **k: (calls.append(1), (None, None))[1]
res = sd.detect_text_regions(rot, 7.0)
sd._ocr = real
ok(res["subtitle"] is None and res["watermarks"] == [] and len(calls) == sd.EARLY_STOP, f"no text: stops after {len(calls)} frames, not 13")
# stray text in different frames at different heights must not keep the scan going; a subtitle band must
ok(not sd._recurring([(0, .1, .20, .3, .24, "a", .9), (3, .1, .60, .3, .64, "b", .9)]), "recurring: text at different heights is not a subtitle")
ok(sd._recurring([(0, .1, .80, .9, .84, "a", .9), (4, .1, .81, .9, .85, "b", .9)]), "recurring: same height in 2 frames = subtitle-like, keep scanning")
# keyframes too far apart (one keyframe in the whole clip): the first pictures are identical -> the exact reader takes over and the pictures differ
one = f"{tmp}/one.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=6", "-c:v", "libx264", "-g", "9999", "-pix_fmt", "yuv420p", one], check=True)
src1 = sd._Frames(one, 6.0, 12)
src1.prepare(list(range(0, 12, 2)))
a, b = src1.get(0), src1.get(10)
ok(not src1.fast and a is not None and b is not None and (a != b).any(), "one keyframe only: switches to exact reading, pictures differ")
import scene_cuts  # noqa: E402
ok(scene_cuts._skip_args(rot) == ["-skip_frame", "nokey"], "scene cuts: a 4K clip is scanned on keyframes only")
ok(scene_cuts._skip_args(one) == [], "scene cuts: a small clip keeps the exact scan")
t = time.time(); scene_cuts.detect_cuts(rot); ok(time.time() - t < 20, f"scene cuts on the 4K clip took {time.time() - t:.1f}s")
print("ALL OK")
