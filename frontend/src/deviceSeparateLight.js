// Light speech removal on the user's device: Spleeter 2-stems (Deezer, ONNX export from the sherpa-onnx project), two small models.
// 44.1 kHz stereo -> STFT (4096 / hop 1024) -> loudness of the lowest 1024 bins (0-11 kHz), 512 frames (~11.9 s) at a time ->
// each model guesses its part (speech / everything else) -> the share that is NOT speech is kept from the original spectrum.
// Same maths as the Python prototype (spleeter_sep.py); checked against it. Much lighter than the MDX-Net model in deviceSeparate.js.
import { loadOrt } from './deviceSeparate.js';

export const LIGHT_MODELS = { vocals: '/models/spleeter/vocals.onnx', accompaniment: '/models/spleeter/accompaniment.onnx' };
const SR = 44100, N = 4096, HOP = 1024, F = 1024, T = 512, BINS = N / 2 + 1, PAD = N / 2;

const cosT = new Float64Array(N / 2), sinT = new Float64Array(N / 2), rev = new Uint32Array(N), WIN = new Float64Array(N);
for (let i = 0; i < N / 2; i++) { cosT[i] = Math.cos(2 * Math.PI * i / N); sinT[i] = -Math.sin(2 * Math.PI * i / N); }
for (let i = 0; i < N; i++) { let r = 0; for (let b = 0; b < 12; b++) r |= ((i >> b) & 1) << (11 - b); rev[i] = r; WIN[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / N); }

function fft(re, im) {   // in place, length N
  for (let i = 0; i < N; i++) { const j = rev[i]; if (j > i) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
  for (let size = 2; size <= N; size *= 2) {
    const half = size / 2, stride = N / size;
    for (let s = 0; s < N; s += size) {
      for (let k = 0; k < half; k++) {
        const wr = cosT[k * stride], wi = sinT[k * stride], a = s + k, b = a + half;
        const xr = re[b] * wr - im[b] * wi, xi = re[b] * wi + im[b] * wr;
        re[b] = re[a] - xr; im[b] = im[a] - xi; re[a] += xr; im[a] += xi;
      }
    }
  }
}

/** audio: { left, right } Float32Array at 44.1 kHz. models: { vocals, accompaniment } ArrayBuffers. backend: 'webgpu' | 'wasm'. */
export async function separateLight(audio, models, backend, { threads, onProgress, onStage } = {}) {
  const ort = await loadOrt();
  ort.env.wasm.numThreads = globalThis.crossOriginIsolated ? Math.max(1, Math.min(threads || navigator.hardwareConcurrency || 4, 8)) : 1;
  const t0 = performance.now();
  if (onStage) onStage('starting model 1 of 2');
  const sv = await ort.InferenceSession.create(models.vocals, { executionProviders: [backend], graphOptimizationLevel: 'all' });
  if (onStage) onStage('starting model 2 of 2');
  const sa = await ort.InferenceSession.create(models.accompaniment, { executionProviders: [backend], graphOptimizationLevel: 'all' });
  const loadSeconds = (performance.now() - t0) / 1000;
  const total = audio.left.length, frames = 1 + Math.floor(total / HOP), splits = Math.max(1, Math.ceil(frames / T));
  const src = [audio.left, audio.right];
  const sample = (x, i) => { let j = i - PAD; if (j < 0) j = -j; if (j >= total) j = 2 * (total - 1) - j; return j >= 0 && j < total ? x[j] : 0; };   // reflect at both ends
  const acc = [new Float32Array(total + N), new Float32Array(total + N)], norm = new Float32Array(total + N);
  const specRe = new Float32Array(2 * T * BINS), specIm = new Float32Array(2 * T * BINS), mag = new Float32Array(2 * T * F);
  const re = new Float64Array(N), im = new Float64Array(N);
  let modelMs = 0, mathMs = 0, firstSeconds = null;
  const t1 = performance.now();
  try {
    for (let s = 0; s < splits; s++) {
      if (onStage) onStage(`piece ${s + 1} of ${splits}`);
      let m = performance.now();
      const first = s * T, count = Math.min(T, frames - first);
      mag.fill(0);
      for (let c = 0; c < 2; c++) {
        for (let t = 0; t < count; t++) {
          const o = (first + t) * HOP, x = src[c];
          if (o >= PAD && o + N - PAD <= total) { for (let i = 0, j = o - PAD; i < N; i++, j++) { re[i] = x[j] * WIN[i]; } }
          else for (let i = 0; i < N; i++) re[i] = sample(x, o + i) * WIN[i];
          im.fill(0); fft(re, im);
          const base = (c * T + t) * BINS, mb = (c * T + t) * F;
          for (let f = 0; f < BINS; f++) { specRe[base + f] = re[f]; specIm[base + f] = im[f]; }
          for (let f = 0; f < F; f++) mag[mb + f] = Math.hypot(re[f], im[f]);
        }
      }
      mathMs += performance.now() - m; m = performance.now();
      const feed = () => ({ x: new ort.Tensor('float32', mag, [2, 1, T, F]) });
      const rv = await sv.run(feed()), v = rv.y.getData ? await rv.y.getData() : rv.y.data;
      const ra = await sa.run(feed()), a = ra.y.getData ? await ra.y.getData() : ra.y.data;
      modelMs += performance.now() - m; m = performance.now();
      for (let c = 0; c < 2; c++) {
        for (let t = 0; t < count; t++) {
          const base = (c * T + t) * BINS, mb = (c * T + t) * F;
          let hi = 0;
          for (let f = 0; f < F; f++) {
            const vv = v[mb + f] * v[mb + f], aa = a[mb + f] * a[mb + f], keep = (aa + 5e-11) / (vv + aa + 1e-10);   // share that is not speech
            re[f] = specRe[base + f] * keep; im[f] = specIm[base + f] * keep;
            if (f >= 768) hi += keep;
          }
          hi /= (F - 768);                                   // the model stops at 11 kHz: above it use the top band's average
          for (let f = F; f < BINS; f++) { re[f] = specRe[base + f] * hi; im[f] = specIm[base + f] * hi; }
          for (let f = 1; f < N / 2; f++) { re[N - f] = re[f]; im[N - f] = -im[f]; }   // mirror image = a real signal
          for (let i = 0; i < N; i++) im[i] = -im[i];                                  // inverse FFT = conj(FFT(conj(X))) / N
          fft(re, im);
          const o = (first + t) * HOP, y = acc[c];
          for (let i = 0; i < N; i++) y[o + i] += (re[i] / N) * WIN[i];
          if (c === 0) for (let i = 0; i < N; i++) norm[o + i] += WIN[i] * WIN[i];
        }
      }
      mathMs += performance.now() - m;
      if (s === 0) firstSeconds = (performance.now() - t1) / 1000;
      if (onProgress) onProgress(s + 1, splits, (performance.now() - t1) / 1000);
      await new Promise((r) => setTimeout(r, 0));
    }
  } finally { for (const x of [sv, sa]) { try { await x.release(); } catch (e) { /* ignore */ } } }
  const out = [new Float32Array(total), new Float32Array(total)];
  for (let c = 0; c < 2; c++) for (let i = 0; i < total; i++) out[c][i] = acc[c][i + PAD] / Math.max(norm[i + PAD], 1e-8);
  const seconds = (performance.now() - t1) / 1000, audioSeconds = total / SR;
  return {
    left: out[0], right: out[1],
    stats: {
      model: 'light (Spleeter)', backend, threads: backend === 'wasm' ? ort.env.wasm.numThreads : null,
      audioSeconds: +audioSeconds.toFixed(1), seconds: +seconds.toFixed(1), timesRealTime: +(audioSeconds / seconds).toFixed(2),
      tenMinuteFilmMinutes: +((600 / (audioSeconds / seconds)) / 60).toFixed(1),
      modelLoadSeconds: +loadSeconds.toFixed(1), firstChunkSeconds: firstSeconds && +firstSeconds.toFixed(1),
      modelSeconds: +(modelMs / 1000).toFixed(1), mathSeconds: +(mathMs / 1000).toFixed(1), chunks: splits,
      jsHeapMB: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1e6) : null,
    },
  };
}
