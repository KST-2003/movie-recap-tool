"""Offline test: a film with MANY scenes (the 10-minute one had 161) must be rendered with a handful of ffmpeg inputs, not one per voice clip
(that hit the service's 200-thread cap: "pthread_create() failed"), and each voice clip must still land in its own scene.
Run: python test_many_scenes.py"""
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


N, SCENE = 160, 0.48   # 12 frames at 25 fps: whole frames per scene, so no rounding drift
src = f"{tmp}/src.mp4"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s=360x640:r=25:d={N * SCENE}", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
                "-t", str(N * SCENE), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
segments, scenes = [], []
for k in range(N):
    freq = 300 + 12 * k
    path = f"{tmp}/clip{k}.wav"
    rate = 24000 if k % 2 else 44100   # mixed sample rates, like the different voice providers
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=f={freq}:r={rate}:d=0.4", "-ac", "1", path], check=True)
    segments.append({"audio_path": path, "translated_text": f"line {k}"})
    scenes.append(r.Scene(src_start=k * SCENE, src_end=(k + 1) * SCENE, out_len=SCENE, audio_index=k, out_start=k * SCENE, audio_len=0.4))

# record every ffmpeg command the render runs
real_run, cmds = subprocess.run, []
def spy(cmd, *a, **kw):
    if cmd and cmd[0] == "ffmpeg":
        cmds.append(list(cmd))
    return real_run(cmd, *a, **kw)
r.subprocess.run = spy

out = f"{tmp}/out.mp4"
res = r.render(src, segments, scenes, r.EffectOptions(captions=False), out, tmp, "t")
r.subprocess.run = real_run
render_cmds = [c for c in cmds if "-filter_complex_script" in c or "-/filter_complex" in c]
most_inputs = max(c.count("-i") for c in render_cmds)
ok(most_inputs <= 4, f"the render uses at most 4 ffmpeg inputs (largest command: {most_inputs}; was {N + 1} before)")
dur = float(real_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
ok(abs(dur - N * SCENE) < 0.3, f"output length {dur:.2f}s matches the plan {N * SCENE}s")
leftovers = [f for f in os.listdir(tmp) if f.endswith("_voice.wav") or "_filter" in f]
ok(not leftovers, "temporary voice track / filter files are removed")

pcm = np.frombuffer(real_run(["ffmpeg", "-v", "error", "-i", out, "-f", "s16le", "-ar", "44100", "-ac", "1", "-"], capture_output=True).stdout, dtype=np.int16).astype(float)
if os.getenv("DBG"):
    for k in range(0, N, 4):
        a = int((k * SCENE + 0.05) * 44100); seg = pcm[a:a + int(0.3 * 44100)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); peak = np.argmax(spec) * 44100 / len(seg)
        print(k, round(peak), "clip", round((peak - 300) / 12))
for k in (0, 1, 37, 80, 121, 159):   # the loudest frequency inside scene k must be clip k's tone
    a = int((k * SCENE + 0.05) * 44100)
    seg = pcm[a:a + int(0.3 * 44100)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    peak = np.argmax(spec) * 44100 / len(seg)
    ok(abs(peak - (300 + 12 * k)) < 10, f"scene {k}: voice tone {peak:.0f} Hz == clip {k} ({300 + 12 * k} Hz)")

# sound only (on-device render): built in scene groups and joined; every clip must still sit in its own scene, with no drift at the joins
aout = f"{tmp}/sound.m4a"
r.render_audio(src, segments, scenes, r.EffectOptions(captions=False), aout, tmp, "s")
adur = float(real_run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", aout], capture_output=True, text=True).stdout)
ok(abs(adur - N * SCENE) < 0.1, f"sound-only length {adur:.2f}s matches the plan {N * SCENE}s")
pcm = np.frombuffer(real_run(["ffmpeg", "-v", "error", "-i", aout, "-f", "s16le", "-ar", "44100", "-ac", "1", "-"], capture_output=True).stdout, dtype=np.int16).astype(float)
for k in (0, 39, 40, 41, 80, 121, 159):   # 40 = first scene of the second group
    a = int((k * SCENE + 0.05) * 44100)
    seg = pcm[a:a + int(0.3 * 44100)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    peak = np.argmax(spec) * 44100 / len(seg)
    ok(abs(peak - (300 + 12 * k)) < 10, f"sound only, scene {k}: tone {peak:.0f} Hz == clip {k} ({300 + 12 * k} Hz)")
    quiet = pcm[int((k * SCENE + 0.42) * 44100):int((k * SCENE + 0.47) * 44100)]   # the clip is 0.4 s: the scene's last part is silent
    ok(np.abs(quiet).max() < 600, f"sound only, scene {k}: silent after its clip (no drift into the next scene)")
ok(not [f for f in os.listdir(tmp) if f.startswith("s_")], "sound-only temporary files are removed")
print("ALL OK")
