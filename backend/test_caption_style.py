"""Offline test of the subtitle style (font, size, colours, box, position): the drawing itself, the strip position, the
device plan and the /rerender API keeping the choice. Run: python test_caption_style.py"""
import os
import subprocess
import tempfile
import time

import numpy as np
from PIL import Image

tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db",
                  TTS_PROVIDER="fake", DUB_PROVIDER="gemini", TTS_BULK="0", ALLOW_SIGNUP="true")
import recap_engine as r  # noqa: E402


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        raise SystemExit(1)


TEXT = "မင်္ဂလာပါ။ ဒီနေ့ အဆင်ပြေလား။"
W, H = 720, 280


def draw(style=None, valign="bottom"):
    path = f"{tmp}/c.png"
    r.render_caption(TEXT, path, W, H, size_px=40, style=style, valign=valign)
    return np.asarray(Image.open(path).convert("RGBA")).astype(int)


def count(img, rgb, tol=40):
    return int(((np.abs(img[:, :, :3] - np.array(rgb)).sum(axis=2) < tol) & (img[:, :, 3] > 200)).sum())


def rows(img):
    ys = np.where(img[:, :, 3].max(axis=1) > 0)[0]
    return int(ys.min()), int(ys.max())


ok(all(os.path.isfile(os.path.join(r._FONT_DIR, f)) for f in r.CAPTION_FONTS.values()), "every style font file is shipped in backend/fonts")
st = r.caption_style({"font": "nope", "size": 9, "color": "red", "bg_opacity": "x", "position": "left", "outline": "zz"})
ok(st == {**r.DEFAULT_CAPTION_STYLE, "size": 1.8, "outline": ""}, f"broken values fall back to the default look ({st})")

base = draw()
ok(count(base, (255, 235, 59)) > 300 and count(base, (255, 0, 0)) == 0, "default: yellow letters")
red = draw({"color": "#FF0000", "outline": ""})
ok(count(red, (255, 0, 0)) > 300 and count(red, (255, 235, 59)) == 0, "text colour is applied")
blue = draw({"bg": "#0000FF", "bg_opacity": 1.0})
ok(count(blue, (0, 0, 255)) > 5000, "box colour + full opacity are applied")
nobox = draw({"bg_opacity": 0})
ok((nobox[:, :, 3] > 0).sum() < (base[:, :, 3] > 0).sum() * 0.5, "opacity 0 = no box")
big, small = draw({"size": 1.5}), draw({"size": 0.7})
hb, hs, h0 = [rows(x)[1] - rows(x)[0] for x in (big, small, base)]
ok(hb > h0 > hs, f"size changes the letters (strip heights {hs} < {h0} < {hb})")
shapes = {f: (draw({"font": f})[:, :, 3] > 128) for f in r.CAPTION_FONTS}
ok(all((shapes["sans"] != shapes[f]).sum() > 200 for f in ("sans-regular", "serif", "padauk")), "each font draws different letters")
top, mid, bot = rows(draw(valign="top")), rows(draw(valign="middle")), rows(base)
ok(top[0] < 20 and bot[1] > H - 20 and abs((mid[0] + mid[1]) / 2 - H / 2) < 12, f"vertical alignment inside the strip (top {top}, middle {mid}, bottom {bot})")

fx = r.EffectOptions(subtitle_rect=(100, 900, 500, 100))
ok(r.caption_box(fx, 720, 1280, False)[1:] == (max(0, 900 + 100 + 12 - int(1280 * 0.22)), "bottom"), "auto: where the original subtitle was")
for pos, want in (("top", 64), ("middle", (1280 - 281) // 2), ("bottom", 1280 - 281 - 51)):
    fx.caption_style = {"position": pos}
    ok(r.caption_box(fx, 720, 1280, False)[1] == want, f"position {pos}: strip top {want}")
fx.caption_style = {"size": 1.8, "font": "serif", "color": "#00FF00"}
plan = r.device_plan({"width": 720, "height": 1280, "fps": 30}, [r.Scene(0, 2, out_len=2)], fx, [(0, 2, TEXT)], 2)
cap = plan["caption"]
ok(cap["style"]["font"] == "serif" and cap["style"]["color"] == "#00FF00" and cap["height"] > int(1280 * 0.22) and "bottom" in cap,
   f"device plan carries the style ({cap})")

# API: Apply in the editor keeps the style, the render uses it, and the next edit starts from it
from fastapi.testclient import TestClient  # noqa: E402

import gemini_dub  # noqa: E402
from main import app  # noqa: E402

video = f"{tmp}/in.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x202020:s=360x640:r=25:d=8", "-f", "lavfi", "-i", "sine=f=300:d=8",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video], check=True)
gemini_dub.dub = lambda path, target, **kw: ("zh", gemini_dub.finish_segments(
    [{"start": i * 4.0, "end": i * 4.0 + 3.5, "source_text": "x", "translated_text": TEXT} for i in range(2)], kw.get("scene_cuts") or []))
c = TestClient(app)
H_ = {"Authorization": "Bearer " + c.post("/api/auth/register", json={"email": "s@example.com", "password": "password123"}).json()["token"]}


def wait(job_id):
    for _ in range(300):
        j = c.get(f"/api/jobs/{job_id}", headers=H_).json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.5)
    raise SystemExit("job did not finish")


with open(video, "rb") as f:
    first = wait(c.post("/api/jobs", headers=H_, files={"video_file": ("in.mp4", f, "video/mp4")}, data={"voice_type": "su", "fit_translation": "false"}).json()["job_id"])
ok(first["status"] == "done" and first["result"]["project"]["fx"]["caption_style"] == r.DEFAULT_CAPTION_STYLE, "a new video has the default style in its project")
lines = [{"id": g["id"], "start": g["start"], "text": g["text"]} for g in first["result"]["project"]["segments"]]
bad = c.post(f"/api/jobs/{first['id']}/rerender", headers=H_, json={"segments": lines, "caption_style": {"color": "red"}})
ok(bad.status_code == 422, "a broken colour is refused")
style = {"font": "padauk", "size": 1.4, "color": "#FF00FF", "outline": "", "bg": "#FFFFFF", "bg_opacity": 0.0, "position": "top"}
second = wait(c.post(f"/api/jobs/{first['id']}/rerender", headers=H_, json={"segments": lines, "caption_style": style}).json()["job_id"])
ok(second["status"] == "done" and second["result"]["project"]["fx"]["caption_style"] == style, "the re-render stores the chosen style")
out = [p for p in os.listdir(f"{tmp}/out") if p.endswith(".mp4") and second["id"] in p][0]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1.5", "-i", f"{tmp}/out/{out}", "-frames:v", "1", f"{tmp}/f.png"], check=True)
frame = np.asarray(Image.open(f"{tmp}/f.png").convert("RGB")).astype(int)
mag = (np.abs(frame - np.array([255, 0, 255])).sum(axis=2) < 140)
ys = np.where(mag.any(axis=1))[0]
ok(mag.sum() > 150 and ys.max() < frame.shape[0] * 0.35, f"the video shows magenta letters near the top ({int(mag.sum())} px, rows {ys.min()}-{ys.max()})")
third = wait(c.post(f"/api/jobs/{second['id']}/rerender", headers=H_, json={"segments": lines, "caption_style": {"size": 1.0}}).json()["job_id"])
ok(third["result"]["project"]["fx"]["caption_style"] == {**style, "size": 1.0}, "a later edit changes only what it sends")
print("ALL OK")
