// Proof of concept for "Render on my device (faster, beta)": the browser builds a 720p MP4 itself (WebCodecs through Mediabunny).
// NOT used by the app yet. Test page: /device-test.html. What it proves: can this device encode fast enough, how much memory it needs,
// and that a caption line + a mixed audio track (original sound lowered + a voice-over clip) come out right.
import {
  ALL_FORMATS, AudioBufferSink, AudioBufferSource, BlobSource, BufferTarget, CanvasSink, CanvasSource, Input,
  Mp4OutputFormat, Output, canEncodeVideo,
} from 'mediabunny';

const even = (n) => Math.max(2, Math.round(n / 2) * 2);

/** Output size: short side = `short` px (never above the source), same shape, even numbers. */
export function outputSize(w, h, short = 720) {
  const k = Math.min(1, short / Math.min(w, h));
  return [even(w * k), even(h * k)];
}

/** Quick test before offering the button: can this browser encode H.264 at 720p, and how many frames per second does it manage? */
export async function capabilityTest(short = 720) {
  const info = { webcodecs: typeof VideoEncoder !== 'undefined' && typeof VideoDecoder !== 'undefined', deviceMemory: navigator.deviceMemory || null,
    cores: navigator.hardwareConcurrency || null };
  if (!info.webcodecs) return { ...info, ok: false, reason: 'WebCodecs is not available in this browser' };
  const [w, h] = [even(short * 16 / 9), even(short)];
  if (!(await canEncodeVideo('avc', { width: w, height: h, bitrate: 3_000_000 }))) return { ...info, ok: false, reason: 'H.264 encoding is not supported' };
  const canvas = new OffscreenCanvas(w, h);
  const ctx = canvas.getContext('2d');
  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const source = new CanvasSource(canvas, { codec: 'avc', bitrate: 3_000_000 });
  output.addVideoTrack(source, { frameRate: 30 });
  await output.start();
  const frames = 60, t0 = performance.now();
  for (let i = 0; i < frames; i++) {   // moving gradient: not a trivially compressible picture
    const g = ctx.createLinearGradient(i * 10 % w, 0, w, h);
    g.addColorStop(0, `hsl(${i * 6},80%,50%)`); g.addColorStop(1, `hsl(${i * 6 + 120},80%,30%)`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
    await source.add(i / 30, 1 / 30);
  }
  await output.finalize();
  const seconds = (performance.now() - t0) / 1000, fps = frames / seconds;
  // 30 fps video needs fps >= 30 to render in real time; below ~15 a long video gets slow
  return { ...info, ok: fps >= 15, fps: Math.round(fps), reason: fps >= 15 ? '' : `encoding only ${Math.round(fps)} frames/s` };
}

function drawCaption(ctx, w, h, text) {
  const size = Math.round(h * 0.034);
  ctx.font = `600 ${size}px "Noto Sans Myanmar", "Myanmar Text", Padauk, sans-serif`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const tw = Math.min(w * 0.9, ctx.measureText(text).width), bh = size * 1.9, y = h * 0.86;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.beginPath(); ctx.roundRect((w - tw) / 2 - size * 0.6, y - bh / 2, tw + size * 1.2, bh, size * 0.4); ctx.fill();
  ctx.fillStyle = '#fff'; ctx.fillText(text, w / 2, y, w * 0.9);
}

/** A short beep standing in for a voice-over clip (a real clip would be decoded with AudioContext.decodeAudioData). */
function beep(ctx, seconds = 1.2) {
  const buf = ctx.createBuffer(1, Math.round(ctx.sampleRate * seconds), ctx.sampleRate), d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.sin(2 * Math.PI * 440 * i / ctx.sampleRate) * 0.4 * Math.min(1, i / 2000, (d.length - i) / 2000);
  return buf;
}

/**
 * Render `file` to a 720p MP4 with a caption (from 1 s to 4 s) and a beep "voice" every 3 s over the lowered original sound.
 * Returns { blob, stats }. onProgress(0..1, text).
 */
export async function renderOnDevice(file, { short = 720, caption = 'မင်္ဂလာပါ။ ဒီဗီဒီယိုကို ကိုယ့်ဖုန်းထဲမှာ ပြုလုပ်နေပါတယ်။', onProgress = () => {} } = {}) {
  const started = performance.now();
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const vTrack = await input.getPrimaryVideoTrack();
  if (!vTrack) throw new Error('No video track');
  const duration = await input.computeDuration();
  const [sw, sh] = [await vTrack.getDisplayWidth(), await vTrack.getDisplayHeight()];   // as shown (rotation applied)
  const [w, h] = outputSize(sw, sh, short);

  const canvas = new OffscreenCanvas(w, h), ctx = canvas.getContext('2d');
  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const vSource = new CanvasSource(canvas, { codec: 'avc', bitrate: Math.round(w * h * 3.2), hardwareAcceleration: 'prefer-hardware' });
  output.addVideoTrack(vSource, { frameRate: 30 });

  // audio: original (lowered) + voice clips, mixed in one offline pass, then encoded
  const aTrack = await input.getPrimaryAudioTrack();
  let aSource = null, mixed = null;
  if (aTrack || true) {
    onProgress(0.02, 'Mixing audio');
    const rate = 48000, off = new OfflineAudioContext(2, Math.ceil(duration * rate), rate);
    if (aTrack) {
      const sink = new AudioBufferSink(aTrack);
      for await (const { buffer, timestamp } of sink.buffers()) {
        const src = off.createBufferSource(), gain = off.createGain();
        gain.gain.value = 0.4; src.buffer = buffer; src.connect(gain).connect(off.destination); src.start(Math.max(0, timestamp));
      }
    }
    const clip = beep(off);
    for (let t = 1; t < duration - 1; t += 3) { const s = off.createBufferSource(); s.buffer = clip; s.connect(off.destination); s.start(t); }
    mixed = await off.startRendering();
    aSource = new AudioBufferSource({ codec: 'aac', bitrate: 128_000 });
    output.addAudioTrack(aSource);
  }

  await output.start();
  const sink = new CanvasSink(vTrack, { width: w, height: h, fit: 'contain' });
  let frames = 0, lastReport = 0;
  for await (const { canvas: frame, timestamp, duration: d } of sink.canvases()) {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h);
    ctx.drawImage(frame, 0, 0, w, h);
    if (timestamp >= 1 && timestamp < 4) drawCaption(ctx, w, h, caption);
    await vSource.add(timestamp, d);
    frames++;
    if (performance.now() - lastReport > 250) { lastReport = performance.now(); onProgress(0.05 + 0.9 * Math.min(1, timestamp / duration), `Frame ${frames}`); }
  }
  if (aSource && mixed) await aSource.add(mixed);
  await output.finalize();
  const seconds = (performance.now() - started) / 1000;
  const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
  const mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
  return { blob, stats: { source: `${sw}x${sh}`, output: `${w}x${h}`, videoSeconds: +duration.toFixed(1), seconds: +seconds.toFixed(1),
    speed: +(duration / seconds).toFixed(2), frames, outputMB: +(blob.size / 1048576).toFixed(1), jsHeapMB: mem } };
}
