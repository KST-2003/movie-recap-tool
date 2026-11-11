// Proof of concept for "Render on my device (faster, beta)": the browser builds a 720p MP4 itself (WebCodecs through Mediabunny).
// NOT used by the app yet. Test page: /device-test.html. What it proves: can this device encode fast enough, how much memory it needs,
// and that a caption line + a mixed audio track (original sound lowered + a voice-over clip) come out right.
import {
  canEncodeAudio, ALL_FORMATS, AudioBufferSink, AudioBufferSource, BlobSource, BufferTarget, CanvasSink, CanvasSource, Input,
  Conversion, Mp4OutputFormat, Output, VideoSampleSink, canEncodeVideo,
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
  const aacOk = await canEncodeAudio('aac', { numberOfChannels: 2, sampleRate: 48000, bitrate: 128_000 }).catch(() => false);
  if (!aacOk) return { ...info, ok: false, aac: false, reason: 'AAC audio encoding is not supported' };
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


/**
 * Draws one video frame (+ an optional caption picture) on a canvas that is then encoded. WebGL keeps the frame on the GPU:
 * on an iPhone 16 Pro (Safari) this was 4.4x real time against 0.7x with a 2D canvas (device test, 2026-11-11).
 * Falls back to a normal 2D canvas when WebGL is missing. Rotation / flip of the source (phone clips) are applied here.
 */
function makeCompositor(w, h) {
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const capCanvas = document.createElement('canvas');
  capCanvas.width = w; capCanvas.height = h;
  const capCtx = capCanvas.getContext('2d');
  const gl = canvas.getContext('webgl', { preserveDrawingBuffer: true, alpha: false, antialias: false });
  if (!gl) {
    const ctx = canvas.getContext('2d');
    return { canvas, kind: '2d', capCtx, capCanvas, setCaption() {}, draw(sample, hasCaption) { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h); sample.draw(ctx, 0, 0, w, h); if (hasCaption) ctx.drawImage(capCanvas, 0, 0); } };
  }
  const prog = gl.createProgram();
  const shader = (type, src) => { const o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o); gl.attachShader(prog, o); };
  shader(gl.VERTEX_SHADER, 'attribute vec2 p; varying vec2 uv; void main(){ uv = vec2((p.x+1.)/2., 1.-(p.y+1.)/2.); gl_Position = vec4(p,0.,1.); }');
  shader(gl.FRAGMENT_SHADER, 'precision mediump float; varying vec2 uv; uniform sampler2D t; uniform int rot; uniform int flip;' +
    'void main(){ vec2 d = uv; if (flip == 1) d.x = 1. - d.x; vec2 s = d;' +
    ' if (rot == 90) s = vec2(d.y, 1. - d.x); else if (rot == 180) s = vec2(1. - d.x, 1. - d.y); else if (rot == 270) s = vec2(1. - d.y, d.x);' +
    ' gl_FragColor = texture2D(t, s); }');
  gl.linkProgram(prog); gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const makeTex = () => {
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  };
  const videoTex = makeTex(), capTex = makeTex();
  const uRot = gl.getUniformLocation(prog, 'rot'), uFlip = gl.getUniformLocation(prog, 'flip');
  gl.viewport(0, 0, w, h);
  return {
    canvas, kind: 'webgl', capCtx, capCanvas,
    /** Call after drawing a new caption on capCanvas (capCtx): uploads it as the overlay picture. */
    setCaption() { gl.bindTexture(gl.TEXTURE_2D, capTex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, capCanvas); },
    draw(sample, hasCaption) {
      const frame = sample.toVideoFrame();
      gl.bindTexture(gl.TEXTURE_2D, videoTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, frame);
      frame.close();
      gl.uniform1i(uRot, ((Math.round((sample.rotation || 0) / 90) * 90) % 360 + 360) % 360); gl.uniform1i(uFlip, sample.flip ? 1 : 0);
      gl.disable(gl.BLEND); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (hasCaption) {   // caption picture: premultiplied alpha, no rotation
        gl.uniform1i(uRot, 0); gl.uniform1i(uFlip, 0);
        gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.bindTexture(gl.TEXTURE_2D, capTex); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
    },
  };
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
export async function renderOnDevice(file, { short = 720, caption = 'မင်္ဂလာပါ။ ဒီဗီဒီယိုကို ကိုယ့်ဖုန်းထဲမှာ ပြုလုပ်နေပါတယ်။', onProgress = () => {}, maxSeconds = 0, audio = true } = {}) {
  const started = performance.now();
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const vTrack = await input.getPrimaryVideoTrack();
  if (!vTrack) throw new Error('No video track');
  const duration = maxSeconds ? Math.min(maxSeconds, await input.computeDuration()) : await input.computeDuration();
  const [sw, sh] = [await vTrack.getDisplayWidth(), await vTrack.getDisplayHeight()];   // as shown (rotation applied)
  const [w, h] = outputSize(sw, sh, short);

  const comp = makeCompositor(w, h);
  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const vSource = new CanvasSource(comp.canvas, { codec: 'avc', bitrate: Math.round(w * h * 3.2), hardwareAcceleration: 'prefer-hardware' });
  output.addVideoTrack(vSource, { frameRate: 30 });

  // audio: original (lowered) + voice clips, mixed in one offline pass, then encoded. The mixing starts together with the video loop (below)
  const aTrack = audio ? await input.getPrimaryAudioTrack() : null;
  let aSource = null, mixPromise = null, mixSeconds = 0;
  if (audio) {
    aSource = new AudioBufferSource({ codec: 'aac', bitrate: 128_000 });
    output.addAudioTrack(aSource);
  }
  const mixAudio = async () => {
    const t0 = performance.now();
    const rate = 48000, off = new OfflineAudioContext(2, Math.ceil(duration * rate), rate);
    if (aTrack) {
      // The decoder hands over ~21 ms pieces (8000 of them for 3 minutes). One Web Audio node per piece took 100 s on an iPhone
      // (device test 2026-11-11), so the pieces are first copied into ONE buffer in plain typed arrays and played by a single node.
      const sink = new AudioBufferSink(aTrack);
      let whole = null, srate = 0, chans = 2;
      for await (const { buffer, timestamp } of sink.buffers(0, duration)) {
        if (!whole) {
          srate = buffer.sampleRate;
          whole = off.createBuffer(chans, Math.max(1, Math.ceil(duration * srate)), srate);
        }
        const at = Math.max(0, Math.round(timestamp * srate));
        for (let c = 0; c < chans; c++) {
          const data = buffer.getChannelData(Math.min(c, buffer.numberOfChannels - 1));   // mono -> both channels
          const target = whole.getChannelData(c);
          if (at + data.length <= target.length) target.set(data, at);
          else if (at < target.length) target.set(data.subarray(0, target.length - at), at);
        }
      }
      if (whole) {
        const src = off.createBufferSource(), gain = off.createGain();
        gain.gain.value = 0.4; src.buffer = whole; src.connect(gain).connect(off.destination); src.start(0);   // the offline context resamples to 48 kHz
      }
    }
    const clip = beep(off);
    for (let t = 1; t < duration - 1; t += 3) { const s = off.createBufferSource(); s.buffer = clip; s.connect(off.destination); s.start(t); }
    const mixed = await off.startRendering();
    mixSeconds = (performance.now() - t0) / 1000;
    return mixed;
  };

  await output.start();
  if (audio) mixPromise = mixAudio();   // runs beside the video frames
  // the caption picture is drawn once; it is shown from 1 s to 4 s
  comp.capCtx.clearRect(0, 0, w, h);
  drawCaption(comp.capCtx, w, h, caption);
  comp.setCaption();
  let frames = 0, lastReport = 0;
  const loopStart = performance.now();
  for await (const sample of new VideoSampleSink(vTrack).samples(0, duration)) {
    comp.draw(sample, sample.timestamp >= 1 && sample.timestamp < 4);
    await vSource.add(sample.timestamp, sample.duration || 1 / 30);
    const t = sample.timestamp;
    sample.close();
    frames++;
    if (performance.now() - lastReport > 250) { lastReport = performance.now(); onProgress(0.05 + 0.9 * Math.min(1, t / duration), `Frame ${frames}`); }
  }
  const loopSeconds = (performance.now() - loopStart) / 1000;
  const waitStart = performance.now();
  if (aSource && mixPromise) await aSource.add(await mixPromise);
  const audioWaitSeconds = (performance.now() - waitStart) / 1000;
  const finishStart = performance.now();
  await output.finalize();
  const finishSeconds = (performance.now() - finishStart) / 1000;
  const seconds = (performance.now() - started) / 1000;
  const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
  const mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
  return { blob, stats: { canvas: comp.kind, source: `${sw}x${sh}`, output: `${w}x${h}`, videoSeconds: +duration.toFixed(1), seconds: +seconds.toFixed(1),
    speed: +(duration / seconds).toFixed(2), frames, videoLoopSeconds: +loopSeconds.toFixed(1), audioMixSeconds: +mixSeconds.toFixed(1), audioWaitedSeconds: +audioWaitSeconds.toFixed(1), finishSeconds: +finishSeconds.toFixed(1), outputMB: +(blob.size / 1048576).toFixed(1), jsHeapMB: mem } };
}

/** Speed lab: which way of doing the work is fast on THIS device? Runs each step on the first `seconds` of the file and reports frames per second. */
export async function speedLab(file, seconds = 15, say = () => {}) {
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const vTrack = await input.getPrimaryVideoTrack();
  const total = await input.computeDuration(), n = Math.min(seconds, total);
  const [sw, sh] = [await vTrack.getDisplayWidth(), await vTrack.getDisplayHeight()];
  const [w, h] = outputSize(sw, sh, 720);
  const res = { source: `${sw}x${sh}`, output: `${w}x${h}`, seconds: n };
  const time = async (name, fn) => {
    say(`${name}…`);
    const t0 = performance.now();
    const frames = await fn();
    const sec = (performance.now() - t0) / 1000;
    res[name] = { sec: +sec.toFixed(1), fps: frames ? Math.round(frames / sec) : null, x: +(n / sec).toFixed(2) };
    say(`${name}: ${JSON.stringify(res[name])}`);
  };
  await time('1 decode only', async () => {
    let c = 0;
    for await (const sample of new VideoSampleSink(vTrack).samples(0, n)) { c++; sample.close(); }
    return c;
  });
  await time('2 decode to 720p canvas', async () => {
    let c = 0;
    for await (const _ of new CanvasSink(vTrack, { width: w, height: h, fit: 'contain' }).canvases(0, n)) c++;   // eslint-disable-line no-unused-vars
    return c;
  });
  await time('3 my render, video only', async () => { const r = await renderOnDevice(file, { maxSeconds: n, audio: false }); return r.stats.frames; });
  await time('4 library convert (resize only)', async () => {
    const out = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
    const conv = await Conversion.init({ input, output: out, audio: { discard: true }, trim: { start: 0, end: n },
      video: { width: w, height: h, fit: 'contain', codec: 'avc', bitrate: Math.round(w * h * 3.2), hardwareAcceleration: 'prefer-hardware', forceTranscode: true } });
    await conv.execute();
    return Math.round(n * 30);
  });
  await time('5 library convert + caption drawing', async () => {
    const out = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
    const canvas = new OffscreenCanvas(w, h), ctx = canvas.getContext('2d');
    const conv = await Conversion.init({ input, output: out, audio: { discard: true }, trim: { start: 0, end: n },
      video: { width: w, height: h, fit: 'contain', codec: 'avc', bitrate: Math.round(w * h * 3.2), hardwareAcceleration: 'prefer-hardware', forceTranscode: true,
        process: (sample) => { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h); sample.draw(ctx, 0, 0, w, h); if (sample.timestamp >= 1 && sample.timestamp < 4) drawCaption(ctx, w, h, 'မင်္ဂလာပါ။'); return canvas; },
        processedWidth: w, processedHeight: h } });
    await conv.execute();
    return Math.round(n * 30);
  });
  const conv = (extra, bitrate = Math.round(w * h * 3.2)) => async () => {
    const out = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
    const c = await Conversion.init({ input, output: out, audio: { discard: true }, trim: { start: 0, end: n },
      video: { width: w, height: h, fit: 'contain', codec: 'avc', bitrate, hardwareAcceleration: 'prefer-hardware', forceTranscode: true, ...extra } });
    await c.execute();
    return Math.round(n * 30);
  };
  await time('4b convert, realtime latency', conv({ latencyMode: 'realtime' }));
  await time('4c convert, baseline profile', conv({ fullCodecString: 'avc1.42E01F' }));
  await time('4d convert, 1.5 Mbps realtime', conv({ latencyMode: 'realtime' }, 1_500_000));
  await time('7 page canvas (not offscreen) + captions', () => canvasVariant(vTrack, n, w, h, 'dom'));
  await time('8 WebGL canvas + captions', () => canvasVariant(vTrack, n, w, h, 'webgl'));
  await time('6 audio mix only', async () => { const r = await renderOnDevice(file, { maxSeconds: Math.min(n, 3), audio: true }); return 0 * r.stats.frames; });
  return res;
}

/** Decode -> draw on a canvas (a normal page canvas, or WebGL) -> encode. Shows which kind of canvas is fast on this device. */
async function canvasVariant(vTrack, n, w, h, kind) {
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  let draw, gl;
  const capCanvas = document.createElement('canvas');
  capCanvas.width = w; capCanvas.height = h;
  drawCaption(capCanvas.getContext('2d'), w, h, 'မင်္ဂလာပါ။ ဒီဗီဒီယိုကို');
  if (kind === 'dom') {
    const ctx = canvas.getContext('2d');
    draw = (sample, cap) => { ctx.fillStyle = '#000'; ctx.fillRect(0, 0, w, h); sample.draw(ctx, 0, 0, w, h); if (cap) ctx.drawImage(capCanvas, 0, 0); };
  } else {
    gl = canvas.getContext('webgl', { preserveDrawingBuffer: true, alpha: false });
    if (!gl) throw new Error('WebGL not available');
    const prog = gl.createProgram();
    const sh = (type, src) => { const o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o); gl.attachShader(prog, o); };
    sh(gl.VERTEX_SHADER, 'attribute vec2 p; varying vec2 uv; void main(){ uv = vec2((p.x+1.)/2., 1.-(p.y+1.)/2.); gl_Position = vec4(p,0.,1.); }');
    sh(gl.FRAGMENT_SHADER, 'precision mediump float; varying vec2 uv; uniform sampler2D t; void main(){ gl_FragColor = texture2D(t, uv); }');
    gl.linkProgram(prog); gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const tex = () => { const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); return t; };
    const videoTex = tex(), capTex = tex();
    gl.bindTexture(gl.TEXTURE_2D, capTex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, capCanvas);
    gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    draw = (sample, cap) => {
      const frame = sample.toVideoFrame();
      gl.viewport(0, 0, w, h);
      gl.bindTexture(gl.TEXTURE_2D, videoTex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, frame);
      gl.disable(gl.BLEND); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (cap) { gl.enable(gl.BLEND); gl.bindTexture(gl.TEXTURE_2D, capTex); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4); }
      frame.close();
    };
  }
  const out = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const src = new CanvasSource(canvas, { codec: 'avc', bitrate: Math.round(w * h * 3.2), hardwareAcceleration: 'prefer-hardware' });
  out.addVideoTrack(src, { frameRate: 30 });
  await out.start();
  let c = 0;
  for await (const sample of new VideoSampleSink(vTrack).samples(0, n)) {
    draw(sample, sample.timestamp >= 1 && sample.timestamp < 4);
    await src.add(sample.timestamp, sample.duration || 1 / 30);
    sample.close(); c++;
  }
  await out.finalize();
  return c;
}
