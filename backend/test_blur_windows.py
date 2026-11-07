"""Offline: the source-subtitle blur only shows inside its time windows. Run: python test_blur_windows.py (needs ffmpeg)"""
import subprocess, tempfile, numpy as np, cv2
import recap_engine as re_

tmp = tempfile.mkdtemp()
src = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=25:d=6", "-f", "lavfi", "-i",
                "sine=duration=6", "-pix_fmt", "yuv420p", "-shortest", src], check=True)


def frame(path, t):
    cap = cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); ok, f = cap.read(); cap.release(); return f


def sharp(f):   # detail inside the blurred rect
    r = f[150:230, 20:300]
    return cv2.Laplacian(cv2.cvtColor(r, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()


def run(windows, scenes, name):
    fx = re_.EffectOptions(blur_subtitles=True, captions=False, subtitle_rect=(20, 150, 280, 80), subtitle_windows=windows)
    out = f"{tmp}/{name}.mp4"
    re_.render(src, [], scenes, fx, out, tmp, name)
    return out


one = [re_.Scene(0, 6, out_len=6, out_start=0)]
out = run([(1.0, 2.0), (4.0, 5.0)], one, "w")
s = {t: sharp(frame(out, t)) for t in (0.5, 1.5, 3.0, 4.5, 5.5)}
print(s)
assert s[1.5] < s[0.5] * 0.5 and s[4.5] < s[3.0] * 0.5 and s[5.5] > s[1.5] * 2, "blur only inside the windows"
# several scenes (source time must stay right when the scenes are cut and joined)
three = [re_.Scene(0, 2, out_len=2, out_start=0), re_.Scene(2, 4, out_len=2, out_start=2), re_.Scene(4, 6, out_len=2, out_start=4)]
out = run([(1.0, 2.0), (4.0, 5.0)], three, "m")
s = {t: sharp(frame(out, t)) for t in (0.5, 1.5, 3.0, 4.5, 5.5)}
print(s)
assert s[1.5] < s[0.5] * 0.5 and s[4.5] < s[3.0] * 0.5 and s[5.5] > s[1.5] * 2
# no windows given = always blurred (old behaviour); empty list = never
a = sharp(frame(run(None, one, "a"), 3.0)); n = sharp(frame(run([], one, "n"), 3.0))
assert a < n * 0.5, (a, n)
print("ALL OK")
