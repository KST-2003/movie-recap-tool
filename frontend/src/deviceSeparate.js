// Proof of concept: remove the original speech from a film's sound ON THE USER'S DEVICE.
// Model: MDX-Net (UVR-MDX-NET-Inst_HQ_3, ONNX) through onnxruntime-web: WebGPU when the browser has it, else WebAssembly (CPU).
// The maths (STFT -> model -> inverse STFT, ~5.9 s chunks) is the same as the Python test (onnx_separate.py); checked against it.
// Not linked from the app. Test page: /separate-test.html

export const MODEL_URL = '/models/UVR-MDX-NET-Inst_HQ_3.onnx';
const SR = 44100, HOP = 1024, N_FFT = 6144, DIM_F = 3072, DIM_T = 256, COMPENSATE = 1.022;
const CHUNK = HOP * (DIM_T - 1), TRIM = N_FFT / 2, STEP = CHUNK - 2 * TRIM;

// ---- FFT of 6144 points = 3 x 2048: three power-of-two FFTs of the interleaved thirds, then combined --------------------
const M = N_FFT / 3;
const cosM = new Float64Array(M / 2), sinM = new Float64Array(M / 2);
for (let i = 0; i < M / 2; i++) { cosM[i] = Math.cos(2 * Math.PI * i / M); sinM[i] = -Math.sin(2 * Math.PI * i / M); }
const rev = new Uint32Array(M);
for (let i = 0, bits = Math.log2(M); i < M; i++) { let r = 0; for (let b = 0; b < bits; b++) r |= ((i >> b) & 1) << (bits - 1 - b); rev[i] = r; }
const cosN = new Float64Array(N_FFT), sinN = new Float64Array(N_FFT);
for (let i = 0; i < N_FFT; i++) { cosN[i] = Math.cos(2 * Math.PI * i / N_FFT); sinN[i] = -Math.sin(2 * Math.PI * i / N_FFT); }
const WINDOW = new Float64Array(N_FFT);
for (let i = 0; i < N_FFT; i++) WINDOW[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N_FFT);

function fft2(re, im) {   // in place, length M (power of two)
  for (let i = 0; i < M; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
  for (let size = 2; size <= M; size *= 2) {
    const half = size / 2, stride = M / size;
    for (let s = 0; s < M; s += size) {
      for (let k = 0; k < half; k++) {
        const wr = cosM[k * stride], wi = sinM[k * stride], a = s + k, b = a + half;
        const xr = re[b] * wr - im[b] * wi, xi = re[b] * wi + im[b] * wr;
        re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
      }
    }
  }
}
const pr = [0, 1, 2].map(() => new Float64Array(M)), pi = [0, 1, 2].map(() => new Float64Array(M));
function fft(inRe, inIm, outRe, outIm) {   // complex FFT, length N_FFT; inIm may be null
  for (let r = 0; r < 3; r++) {
    const a = pr[r], b = pi[r];
    for (let n = 0; n < M; n++) { a[n] = inRe[3 * n + r]; b[n] = inIm ? inIm[3 * n + r] : 0; }
    fft2(a, b);
  }
  for (let k = 0; k < N_FFT; k++) {
    const m = k % M, i1 = k, i2 = (2 * k) % N_FFT;
    outRe[k] = pr[0][m] + pr[1][m] * cosN[i1] - pi[1][m] * sinN[i1] + pr[2][m] * cosN[i2] - pi[2][m] * sinN[i2];
    outIm[k] = pi[0][m] + pr[1][m] * sinN[i1] + pi[1][m] * cosN[i1] + pr[2][m] * sinN[i2] + pi[2][m] * cosN[i2];
  }
}

// ---- one chunk: 2 channels x CHUNK samples -> model input -> model output -> 2 channels x STEP samples -----------------
const fr = new Float64Array(N_FFT), oR = new Float64Array(N_FFT), oI = new Float64Array(N_FFT), sR = new Float64Array(N_FFT), sI = new Float64Array(N_FFT);
const padded = new Float64Array(CHUNK + N_FFT), ola = new Float64Array(CHUNK + N_FFT), norm = new Float64Array(CHUNK + N_FFT);
for (let t = 0; t < DIM_T; t++) for (let i = 0; i < N_FFT; i++) norm[t * HOP + i] += WINDOW[i] * WINDOW[i];

function toSpectrogram(chunk, input) {   // chunk: [Float32Array L, Float32Array R]; input: Float32Array 4 x DIM_F x DIM_T
  const plane = DIM_F * DIM_T;
  for (let c = 0; c < 2; c++) {
    const x = chunk[c];
    for (let i = 0; i < CHUNK; i++) padded[TRIM + i] = x[i];
    for (let i = 0; i < TRIM; i++) { padded[i] = x[TRIM - i]; padded[TRIM + CHUNK + i] = x[CHUNK - 2 - i]; }   // reflect
    for (let t = 0; t < DIM_T; t++) {
      const o = t * HOP;
      for (let i = 0; i < N_FFT; i++) fr[i] = padded[o + i] * WINDOW[i];
      fft(fr, null, oR, oI);
      const re = 2 * c * plane + t, im = (2 * c + 1) * plane + t;
      for (let f = 0; f < DIM_F; f++) { input[re + f * DIM_T] = oR[f]; input[im + f * DIM_T] = oI[f]; }
    }
  }
}

function fromSpectrogram(output, out) {   // out: [Float32Array L, Float32Array R] of STEP samples
  const plane = DIM_F * DIM_T;
  for (let c = 0; c < 2; c++) {
    ola.fill(0);
    for (let t = 0; t < DIM_T; t++) {
      const re = 2 * c * plane + t, im = (2 * c + 1) * plane + t;
      sR.fill(0); sI.fill(0);
      for (let f = 0; f < DIM_F; f++) {            // inverse FFT = conj(FFT(conj(X))) / N; the upper half is the mirror image
        const a = output[re + f * DIM_T], b = output[im + f * DIM_T];
        sR[f] = a; sI[f] = -b;
        if (f > 0) { sR[N_FFT - f] = a; sI[N_FFT - f] = b; }
      }
      fft(sR, sI, oR, oI);
      const o = t * HOP;
      for (let i = 0; i < N_FFT; i++) ola[o + i] += (oR[i] / N_FFT) * WINDOW[i];
    }
    const y = out[c];
    for (let i = 0; i < STEP; i++) { const j = TRIM + TRIM + i; y[i] = (ola[j] / Math.max(norm[j], 1e-8)) * COMPENSATE; }
  }
}

// ---- model + runtime ---------------------------------------------------------------------------------------------------
let ortPromise;
export function loadOrt() {
  if (!ortPromise) ortPromise = import(/* @vite-ignore */ `${location.origin}/ort/ort.webgpu.min.mjs`).then((ort) => { ort.env.wasm.wasmPaths = '/ort/'; return ort; });
  return ortPromise;
}

export async function deviceInfo() {
  const info = {
    browser: navigator.userAgent,
    cpuThreads: navigator.hardwareConcurrency || null,
    memoryHintGB: navigator.deviceMemory || null,                 // Chrome only, capped at 8
    threadsAllowed: !!globalThis.crossOriginIsolated,             // WebAssembly threads need a cross-origin isolated page
    webgpu: false, gpu: null,
  };
  try {
    if (navigator.gpu) {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) { info.webgpu = true; const i = adapter.info || {}; info.gpu = [i.vendor, i.architecture, i.device, i.description].filter(Boolean).join(' ') || 'yes'; }
    }
  } catch (e) { info.gpu = 'error: ' + (e && e.message || e); }
  return info;
}

export async function fetchModel(onProgress, url = MODEL_URL) {   // downloaded once, then kept by the browser (Cache API)
  let cache = null;
  try { cache = await caches.open('separation-model-v1'); const hit = await cache.match(url); if (hit) return { bytes: await hit.arrayBuffer(), cached: true }; } catch (e) { cache = null; }
  const res = await fetch(url);
  if (!res.ok || (res.headers.get('content-type') || '').includes('text/html')) throw new Error('The model file is not on this server (' + url + ').');
  const total = Number(res.headers.get('content-length')) || 0;
  let bytes;
  if (total && res.body) {                      // written straight into one buffer: no second copy in memory
    bytes = new Uint8Array(total);
    const reader = res.body.getReader();
    for (let got = 0; ;) { const { done, value } = await reader.read(); if (done) break; bytes.set(value, got); got += value.length; if (onProgress) onProgress(got / total); }
  } else bytes = new Uint8Array(await res.arrayBuffer());
  try { if (cache) await cache.put(url, new Response(bytes, { headers: { 'content-type': 'application/octet-stream' } })); } catch (e) { /* no room: fine */ }
  return { bytes: bytes.buffer, cached: false };
}

async function resample(channels, rate, length) {   // -> 44.1 kHz stereo
  const frames = Math.max(1, Math.round(length * SR));
  if (rate === SR) { const cut = (x) => (x.length === frames ? x : x.subarray(0, Math.min(x.length, frames))); return { left: cut(channels[0]), right: cut(channels[1]) }; }
  const Off = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const off = new Off(2, frames, SR), buf = off.createBuffer(2, channels[0].length, rate);
  buf.getChannelData(0).set(channels[0]); buf.getChannelData(1).set(channels[1]);
  const node = off.createBufferSource(); node.buffer = buf; node.connect(off.destination); node.start(0);
  const res = await off.startRendering();
  return { left: res.getChannelData(0), right: res.getChannelData(1) };
}

async function decodeWithMediabunny(file, seconds) {   // reads only the sound track, and only the part that is needed
  const { Input, BlobSource, ALL_FORMATS, AudioBufferSink } = await import('mediabunny');
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const track = await input.getPrimaryAudioTrack();
  if (!track) throw new Error('this file has no sound track');
  const sourceDuration = await input.computeDuration(), length = Math.min(sourceDuration, seconds || sourceDuration);
  let rate = 0, left = null, right = null, got = 0;
  for await (const { buffer, timestamp } of new AudioBufferSink(track).buffers(0, length)) {
    if (!rate) { rate = buffer.sampleRate; left = new Float32Array(Math.ceil(length * rate) + rate); right = new Float32Array(left.length); }
    const at = Math.max(0, Math.round(timestamp * rate)), room = left.length - at;
    if (room <= 0) break;
    const l = buffer.getChannelData(0), r = buffer.getChannelData(Math.min(1, buffer.numberOfChannels - 1)), n = Math.min(l.length, room);
    left.set(n === l.length ? l : l.subarray(0, n), at); right.set(n === r.length ? r : r.subarray(0, n), at);
    got = Math.max(got, at + n);
  }
  if (!got) throw new Error('no sound could be decoded');
  const used = Math.min(length, got / rate);
  return { ...(await resample([left.subarray(0, got), right.subarray(0, got)], rate, used)), duration: used, sourceDuration, decoder: 'mediabunny' };
}

async function decodeWithWebAudio(file, seconds) {   // loads the whole file into memory: fine for short clips only
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  let buf;
  try { buf = await ctx.decodeAudioData(await file.arrayBuffer()); } finally { ctx.close(); }
  const length = Math.min(buf.duration, seconds || buf.duration);
  const l = buf.getChannelData(0), r = buf.getChannelData(Math.min(1, buf.numberOfChannels - 1)), n = Math.min(l.length, Math.round(length * buf.sampleRate));
  return { ...(await resample([l.subarray(0, n), r.subarray(0, n)], buf.sampleRate, length)), duration: length, sourceDuration: buf.duration, decoder: 'web audio' };
}

export async function decodeAudio(file, seconds) {   // -> { left, right, duration, sourceDuration, decoder } at 44.1 kHz stereo, first `seconds` only (0 = all)
  let first;
  try { return await decodeWithMediabunny(file, seconds); } catch (e) { first = e; }
  try { return await decodeWithWebAudio(file, seconds); } catch (e) {   // iPhone Safari says only "Decoding failed" for video files
    throw new Error(`could not read the sound of this file (${first && first.message || first}; ${e && e.message || e})`);
  }
}

/** backend: 'webgpu' | 'wasm'. Returns { left, right, stats }. onProgress(done, total, secondsSoFar). */
export async function separate(audio, modelBytes, backend, { threads, onProgress } = {}) {
  const ort = await loadOrt();
  const isolated = !!globalThis.crossOriginIsolated;
  ort.env.wasm.numThreads = isolated ? Math.max(1, Math.min(threads || navigator.hardwareConcurrency || 4, 8)) : 1;
  const t0 = performance.now();
  const session = await ort.InferenceSession.create(modelBytes, { executionProviders: [backend], graphOptimizationLevel: 'all' });
  const loadSeconds = (performance.now() - t0) / 1000;
  const name = session.inputNames[0], outName = session.outputNames[0];
  const total = audio.left.length, chunks = Math.max(1, Math.ceil(total / STEP));
  const outL = new Float32Array(total), outR = new Float32Array(total);
  const input = new Float32Array(4 * DIM_F * DIM_T), piece = [new Float32Array(CHUNK), new Float32Array(CHUNK)], res = [new Float32Array(STEP), new Float32Array(STEP)];
  let modelMs = 0, mathMs = 0, firstChunkSeconds = null;
  const t1 = performance.now();
  try {
    for (let k = 0; k < chunks; k++) {
      const a = k * STEP - TRIM, lo = Math.max(a, 0), hi = Math.min(a + CHUNK, total);
      piece[0].fill(0); piece[1].fill(0);
      piece[0].set(audio.left.subarray(lo, hi), lo - a); piece[1].set(audio.right.subarray(lo, hi), lo - a);
      let m = performance.now();
      toSpectrogram(piece, input);
      mathMs += performance.now() - m; m = performance.now();
      const result = await session.run({ [name]: new ort.Tensor('float32', input, [1, 4, DIM_F, DIM_T]) });
      const data = result[outName].getData ? await result[outName].getData() : result[outName].data;
      modelMs += performance.now() - m; m = performance.now();
      fromSpectrogram(data, res);
      mathMs += performance.now() - m;
      const keep = Math.min(STEP, total - k * STEP);
      outL.set(res[0].subarray(0, keep), k * STEP); outR.set(res[1].subarray(0, keep), k * STEP);
      if (k === 0) firstChunkSeconds = (performance.now() - t1) / 1000;
      if (onProgress) onProgress(k + 1, chunks, (performance.now() - t1) / 1000);
      await new Promise((r) => setTimeout(r, 0));   // let the page breathe
    }
  } finally { try { await session.release(); } catch (e) { /* ignore */ } }
  const seconds = (performance.now() - t1) / 1000, audioSeconds = total / SR;
  const mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null;   // Chrome only; does not include GPU / WebAssembly memory
  return {
    left: outL, right: outR,
    stats: {
      backend, threads: backend === 'wasm' ? ort.env.wasm.numThreads : null,
      audioSeconds: +audioSeconds.toFixed(1), seconds: +seconds.toFixed(1),
      timesRealTime: +(audioSeconds / seconds).toFixed(2),          // 2 = twice as fast as playing it
      tenMinuteFilmMinutes: +((600 / (audioSeconds / seconds)) / 60).toFixed(1),
      modelLoadSeconds: +loadSeconds.toFixed(1), firstChunkSeconds: firstChunkSeconds && +firstChunkSeconds.toFixed(1),
      modelSeconds: +(modelMs / 1000).toFixed(1), mathSeconds: +(mathMs / 1000).toFixed(1), chunks, jsHeapMB: mem,
    },
  };
}

export function toWav(left, right) {
  const n = left.length, buf = new ArrayBuffer(44 + n * 4), v = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); v.setUint32(4, 36 + n * 4, true); str(8, 'WAVEfmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 2, true);
  v.setUint32(24, SR, true); v.setUint32(28, SR * 4, true); v.setUint16(32, 4, true); v.setUint16(34, 16, true); str(36, 'data'); v.setUint32(40, n * 4, true);
  for (let i = 0, o = 44; i < n; i++, o += 4) {
    v.setInt16(o, Math.max(-1, Math.min(1, left[i])) * 32767, true); v.setInt16(o + 2, Math.max(-1, Math.min(1, right[i])) * 32767, true);
  }
  return new Blob([buf], { type: 'audio/wav' });
}
