"""Offline: layer order of logo and subtitle. Default = subtitle drawn over the logo; logo_above_captions = logo over the subtitle.
A solid red logo is placed over the caption strip of a rendered clip and the pixels are read back. Run: python test_layer_order.py"""
import os, subprocess, tempfile
import numpy as np
from PIL import Image
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db")
import recap_engine as r  # noqa: E402

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

W, H = 360, 640
src, logo = f"{tmp}/src.mp4", f"{tmp}/logo.png"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}:r=25:d=3", "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
Image.new("RGB", (200, 200), (255, 0, 0)).save(logo)
sc = r.Scene(0.0, 3.0, out_len=3.0, audio_index=0, audio_len=2.8, text="မင်္ဂလာပါ မင်္ဂလာပါ မင်္ဂလာပါ မင်္ဂလာပါ။")
style = {"color": "#00FF00", "outline": "", "bg": "#0000FF", "bg_opacity": 1.0, "position": "bottom", "size": 1.4}   # a solid blue box with green text

def render(above):
    out = f"{tmp}/{'a' if above else 'b'}.mp4"
    fx = r.EffectOptions(captions=True, caption_style=style, source_audio=True, logo_path=logo, logo_width_frac=0.9,
                         logo_xy=(0.05, 0.55), logo_above_captions=above)   # the logo covers the whole caption strip
    res = r._render_single(src, [{"start": 0.0}], [sc], fx, out, tmp, "t")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1.5", "-i", out, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int), res

img, res = render(False)
ok(len(res["cues"]) >= 1, "the clip has a subtitle")
cap_h, top, _ = r.caption_box(r.EffectOptions(caption_style=style), W, H, False)
strip = img[top:top + cap_h, 40:W - 40]
blue = int(((strip[..., 2] > 150) & (strip[..., 0] < 90)).sum()); red = int(((strip[..., 0] > 150) & (strip[..., 2] < 90)).sum())
ok(blue > 2000, f"default: the subtitle's box is visible over the logo ({blue} blue pixels in the caption strip)")
img2, _ = render(True)
strip2 = img2[top:top + cap_h, 40:W - 40]
blue2 = int(((strip2[..., 2] > 150) & (strip2[..., 0] < 90)).sum()); red2 = int(((strip2[..., 0] > 150) & (strip2[..., 2] < 90)).sum())
ok(blue2 < blue * 0.05 and red2 > red + 2000, f"logo above subtitle: the logo covers it ({blue2} blue, {red2} red; before {blue} blue, {red} red)")
plan = lambda above: r.device_plan({"width": W, "height": H, "fps": 25}, [sc], r.EffectOptions(logo_path=logo, logo_above_captions=above), [], 3.0)
ok(plan(False)["logo"]["above"] is False and plan(True)["logo"]["above"] is True, "the device plan carries the layer order")
print("ALL OK")
