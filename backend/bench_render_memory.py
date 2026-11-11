"""Peak memory + time of the final render for a film-sized job (many scenes), with the same options as a real Full-movie job:
9:16 fit with blurred background at 720p, source subtitle blur, captions, voice clips from the scenes.
Why: a 10-minute film with ~160 scenes made ONE ffmpeg grow ~200 MB per minute (1.3 GB+) on the 1-CPU server and stall at the memory limit.
Run: python bench_render_memory.py VIDEO [SCENES=160]   (env PARALLEL_RENDER_MIN_SECONDS etc. as on the server)
Prints the largest ffmpeg's peak memory (RUSAGE_CHILDREN max) and the wall time."""
import os
import random
import resource
import subprocess
import sys
import tempfile
import time

video, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 160
tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=f"{tmp}/data", UPLOAD_DIR=f"{tmp}/up", OUTPUT_DIR=f"{tmp}/out", DATABASE_URL=f"sqlite:///{tmp}/t.db")
import recap_engine as r  # noqa: E402

info = r.probe_video(video)
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video], capture_output=True, text=True).stdout)
random.seed(3)
cuts = sorted(random.uniform(1, dur - 1) for _ in range(n - 1))
bounds = [0.0] + cuts + [dur]
clip = f"{tmp}/clip.wav"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:r=24000:d=2.5", "-ac", "1", clip], check=True)
segments = [{"audio_path": clip, "translated_text": f"မင်္ဂလာပါ {k}"} for k in range(n)]
scenes, out = [], 0.0
for k in range(n):
    length = bounds[k + 1] - bounds[k]
    scenes.append(r.Scene(src_start=bounds[k], src_end=bounds[k + 1], out_len=length, audio_index=k, out_start=out, audio_len=min(2.5, length), text=f"မင်္ဂလာပါ {k}"))
    out += length
W, H = info["width"], info["height"]
fx = r.EffectOptions(blur_subtitles=True, subtitle_rect=(0, int(H * 0.78), W, int(H * 0.08)), subtitle_windows=[(0.0, dur)],
                     out_size=(720, 1280), fit_mode="blur", captions=True, caption_px=44,
                     background_path=video, duck_background=True, background_volume=0.7)   # Full mode default on the server: the film's own sound, ducked under the voice
t0 = time.time()
res = r.render(video, segments, scenes, fx, f"{tmp}/result.mp4", tmp, "bench")
wall = time.time() - t0
peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
peak_mb = peak / 1048576 if sys.platform == "darwin" else peak / 1024
size = os.path.getsize(f"{tmp}/result.mp4") / 1e6
print(f"{n} scenes, {dur:.0f}s film -> peak child memory {peak_mb:.0f} MB, wall {wall:.0f}s, result {size:.0f} MB, length {res['duration']:.1f}s")
