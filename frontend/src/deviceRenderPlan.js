// "Render on my device": the phone draws the picture from the server's RENDER PLAN (timeline, effects, caption cues) and takes the
// finished sound (voice-over + background, an AAC file made by the server with the same filter graph as a full render) as it is.
// WebCodecs through Mediabunny; WebGL does reframe / blurs / flip / grading, a 2D canvas draws captions + logo as one overlay texture.
// Any failure throws: the caller falls back to the server render (and reports it).
import { DEFAULT_CAPTION_STYLE, loadCaptionFont, rgba } from './captionFonts.js';
import {
  ALL_FORMATS, BlobSource, BufferTarget, CanvasSource, EncodedAudioPacketSource, EncodedPacketSink, Input, Mp4OutputFormat, Output,
  VideoSampleSink, canEncodeVideo,
} from 'mediabunny';

const even = (n) => Math.max(2, Math.round(n / 2) * 2);

const FRAG = `precision highp float;
varying vec2 uv; uniform sampler2D t;
uniform int mode;            // 0 picture, 1 blurred background, 2 blur of the finished frame (manual boxes), 3 overlay texture
uniform int rot; uniform int flip;
uniform vec2 bgScale; uniform vec2 vis; uniform vec2 pan;
uniform vec2 bgStep; uniform vec2 rectStep; uniform vec2 frameStep;
uniform vec4 srcRects[8]; uniform int nSrc; uniform vec4 subRect; uniform int subOn;
uniform vec3 grade;          // brightness, contrast, saturation
vec4 fetch(vec2 d) {
  vec2 s = d;
  if (rot == 90) s = vec2(d.y, 1. - d.x); else if (rot == 180) s = vec2(1. - d.x, 1. - d.y); else if (rot == 270) s = vec2(1. - d.y, d.x);
  return texture2D(t, s);
}
vec4 blurAt(vec2 d, vec2 st) {
  vec4 a = vec4(0.);
  for (int i = -2; i <= 2; i++) for (int j = -2; j <= 2; j++) a += fetch(clamp(d + vec2(float(i), float(j)) * st * 0.5, 0., 1.));
  return a / 25.;
}
bool inRect(vec2 d, vec4 r) { return d.x >= r.x && d.x <= r.x + r.z && d.y >= r.y && d.y <= r.y + r.w; }
void main() {
  if (mode == 3) { gl_FragColor = texture2D(t, uv); return; }
  if (mode == 2) {
    vec2 p = vec2(uv.x, 1. - uv.y); vec4 a = vec4(0.);
    for (int i = -2; i <= 2; i++) for (int j = -2; j <= 2; j++) a += texture2D(t, clamp(p + vec2(float(i), float(j)) * frameStep * 0.5, 0., 1.));
    gl_FragColor = vec4((a / 25.).rgb, 1.); return;
  }
  vec2 d = (mode == 1) ? 0.5 + (uv - 0.5) * bgScale : pan * (1. - vis) + uv * vis;
  if (flip == 1) d.x = 1. - d.x;
  vec4 c;
  if (mode == 1) c = blurAt(d, bgStep);
  else {
    c = fetch(d);
    bool inb = false;
    for (int k = 0; k < 8; k++) { if (k < nSrc && inRect(d, srcRects[k])) inb = true; }
    if (subOn == 1 && inRect(d, subRect)) inb = true;
    if (inb) c = blurAt(d, rectStep);
  }
  vec3 rgb = c.rgb + grade.x;
  rgb = (rgb - 0.5) * grade.y + 0.5;
  float l = dot(rgb, vec3(0.299, 0.587, 0.114));
  gl_FragColor = vec4(clamp(mix(vec3(l), rgb, grade.z), 0., 1.), 1.);
}`;

function makeCompositor(plan) {
  const [W, H] = plan.out;
  const [SW, SH] = plan.source;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const gl = canvas.getContext('webgl', { preserveDrawingBuffer: true, alpha: false, antialias: false });
  if (!gl) throw new Error('WebGL is not available');
  const prog = gl.createProgram();
  const shader = (type, src) => {
    const o = gl.createShader(type); gl.shaderSource(o, src); gl.compileShader(o);
    if (!gl.getShaderParameter(o, gl.COMPILE_STATUS)) throw new Error('Shader: ' + gl.getShaderInfoLog(o));
    gl.attachShader(prog, o);
  };
  shader(gl.VERTEX_SHADER, 'attribute vec2 p; varying vec2 uv; void main(){ uv = vec2((p.x+1.)/2., 1.-(p.y+1.)/2.); gl_Position = vec4(p,0.,1.); }');
  shader(gl.FRAGMENT_SHADER, FRAG);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error('Shader link failed');
  gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const makeTex = () => {
    const t = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    return t;
  };
  const videoTex = makeTex(), overlayTex = makeTex(), frameTex = makeTex();
  const U = (n) => gl.getUniformLocation(prog, n);
  const u = { mode: U('mode'), rot: U('rot'), flip: U('flip'), bgScale: U('bgScale'), vis: U('vis'), pan: U('pan'), bgStep: U('bgStep'),
    rectStep: U('rectStep'), frameStep: U('frameStep'), srcRects: U('srcRects[0]'), nSrc: U('nSrc'), subRect: U('subRect'), subOn: U('subOn'), grade: U('grade') };

  // overlay (captions + logo) on a 2D canvas, uploaded as a premultiplied texture
  const overlay = document.createElement('canvas'); overlay.width = W; overlay.height = H;
  const octx = overlay.getContext('2d');

  // geometry: how the picture sits in the output frame
  const fit = plan.fit_mode === 'crop' ? 'crop' : 'blur';
  const sa = SW / SH, ca = W / H;
  const sameShape = Math.abs(W * SH - H * SW) <= 2 * Math.max(SW, SH);
  let fgVp = [0, 0, W, H], vis = [1, 1], bgScale = [1, 1], needBg = false;
  if (!sameShape) {
    if (fit === 'crop') vis = [Math.min(1, ca / sa), Math.min(1, sa / ca)];
    else {
      const k = Math.min(W / SW, H / SH), fw = Math.round(SW * k), fh = Math.round(SH * k);
      fgVp = [Math.round((W - fw) / 2), Math.round((H - fh) / 2), fw, fh];
      bgScale = [Math.min(1, ca / sa), Math.min(1, sa / ca)];
      needBg = true;
    }
  }
  const blurStep = (px, w, h) => [px / w, px / h];
  const bgStep = [0.025 * bgScale[0], 0.025 * bgScale[1]];   // about 2.5% of the visible picture, like the server's blurred copy
  const sub = plan.subtitle;
  const srcRects = (plan.blur_rects || []).slice(0, 8);
  const flat = new Float32Array(32);
  srcRects.forEach((r, i) => flat.set(r, i * 4));
  const radius = (r) => Math.max(1, Math.min(Math.min(r[2] * SW, r[3] * SH) / 4, 30));
  const rectPx = Math.max(6, ...[...srcRects, ...(sub ? [sub.rect] : [])].map(radius));
  const manualAll = (plan.manual_blurs || []).slice(0, 6), manualTimed = plan.manual_timed || [];
  const grade = plan.grade || {};
  const hasGrade = (grade.brightness || 0) !== 0 || (grade.contrast ?? 1) !== 1 || (grade.saturation ?? 1) !== 1;

  gl.enable(gl.SCISSOR_TEST); gl.scissor(0, 0, W, H);
  let overlayUploaded = false;

  const setMode = (m) => gl.uniform1i(u.mode, m);
  return {
    canvas, overlay, octx,
    uploadOverlay() {
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
      gl.bindTexture(gl.TEXTURE_2D, overlayTex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, overlay);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
      overlayUploaded = true;
    },
    draw(sample, subOn, hasOverlay) {
      const rot = ((Math.round((sample.rotation || 0) / 90) * 90) % 360 + 360) % 360;
      const frame = sample.toVideoFrame();
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, videoTex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, frame);
      frame.close();
      gl.disable(gl.BLEND);
      gl.scissor(0, 0, W, H);
      gl.uniform1i(u.rot, rot); gl.uniform1i(u.flip, plan.flip_h ? 1 : 0);
      gl.uniform3f(u.grade, hasGrade ? grade.brightness || 0 : 0, hasGrade ? grade.contrast ?? 1 : 1, hasGrade ? grade.saturation ?? 1 : 1);
      gl.uniform4fv(u.srcRects, flat); gl.uniform1i(u.nSrc, srcRects.length);
      if (sub) gl.uniform4f(u.subRect, ...sub.rect);
      gl.uniform1i(u.subOn, sub && subOn ? 1 : 0);
      gl.uniform2f(u.pan, ...(plan.pan || [0.5, 0.5]).map((p) => Math.min(Math.max(p, 0), 1)));
      gl.uniform2f(u.rectStep, ...blurStep(rectPx, SW, SH));
      if (needBg) {
        gl.viewport(0, 0, W, H); setMode(1);
        gl.uniform2f(u.bgScale, ...bgScale); gl.uniform2f(u.bgStep, ...bgStep); gl.uniform2f(u.vis, 1, 1);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
      gl.viewport(fgVp[0], H - fgVp[1] - fgVp[3], fgVp[2], fgVp[3]); setMode(0);
      gl.uniform2f(u.vis, ...vis);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.viewport(0, 0, W, H);
      const manual = manualAll.filter((_, k) => subOn || !manualTimed[k]);   // a box over the subtitle follows the blur windows
      if (manual.length) {   // user boxes on the finished frame: copy it, then draw a blurred copy of each box over itself
        gl.bindTexture(gl.TEXTURE_2D, frameTex);
        gl.copyTexImage2D(gl.TEXTURE_2D, 0, gl.RGB, 0, 0, W, H, 0);
        setMode(2); gl.uniform2f(u.frameStep, ...blurStep(Math.max(6, Math.min(30, Math.min(...manual.map((r) => Math.min(r[2], r[3]))) / 4)), W, H));
        for (const [x, y, w, h] of manual) {
          gl.scissor(Math.round(x), Math.round(H - y - h), Math.round(w), Math.round(h));
          gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
        }
        gl.scissor(0, 0, W, H);
      }
      if (hasOverlay && overlayUploaded) {
        setMode(3); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
        gl.bindTexture(gl.TEXTURE_2D, overlayTex); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      }
    },
  };
}

const FONT = '"Noto Sans Myanmar", "Myanmar Sangam MN", "Myanmar Text", Padauk, sans-serif';
let captionFamily = FONT;   // set by renderFromPlan from the plan's subtitle style (the same font file the server draws with)

function wrapText(ctx, text, maxW) {
  let tokens;
  try { tokens = [...new Intl.Segmenter('my', { granularity: 'word' }).segment(text)].map((s) => s.segment); } catch (e) { tokens = text.split(/(\s+)/); }
  const lines = [];
  let cur = '';
  // A piece that is wider than the line on its own (some browsers return a whole Burmese phrase as one "word") is cut into
  // letters (grapheme clusters, so stacked consonants and vowel signs stay together): otherwise the line runs off the picture.
  const pieces = [];
  for (const tok of tokens) {
    if (tok.trim() && ctx.measureText(tok).width > maxW) {
      let letters;
      try { letters = [...new Intl.Segmenter('my', { granularity: 'grapheme' }).segment(tok)].map((g) => g.segment); } catch (e) { letters = Array.from(tok); }
      pieces.push(...letters);
    } else pieces.push(tok);
  }
  for (const tok of pieces) {
    const next = cur + tok;
    if (cur && ctx.measureText(next).width > maxW) { lines.push(cur.trim()); cur = tok.trimStart(); } else cur = next;
  }
  if (cur.trim()) lines.push(cur.trim());
  return lines;
}

function drawOverlay(comp, plan, text, logo) {
  const [W, H] = plan.out;
  const ctx = comp.octx;
  ctx.clearRect(0, 0, W, H);
  const drawLogo = () => {
    if (logo) {
      const lw = Math.round(W * plan.logo.width), lh = Math.round(lw * logo.height / logo.width);
      let x = W - lw - 30, y = 30;
      const pos = plan.logo.pos;
      if (plan.logo.xy) { x = plan.logo.xy[0] * W; y = plan.logo.xy[1] * H; }
      else if (pos === 'top-left') { x = 30; y = 30; } else if (pos === 'bottom-right') { y = H - lh - 30; }
      else if (pos === 'bottom-left') { x = 30; y = H - lh - 30; } else if (pos === 'center') { x = (W - lw) / 2; y = (H - lh) / 2; }
      ctx.drawImage(logo, x, y, lw, lh);
    }
  };
  const drawText = () => {
    if (text) {
      const cap = plan.caption, st = { ...DEFAULT_CAPTION_STYLE, ...(cap.style || {}) };
      let size = cap.size;
      let lines;
      for (;;) {
        ctx.font = `${st.font === 'sans-regular' ? 400 : 700} ${size}px ${captionFamily}`;
        lines = wrapText(ctx, text, plan.caption.max_w);
        if (lines.length <= 3 || size <= 16) break;
        size -= 2;
      }
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      const lh = Math.round(size * 1.75), pad = Math.round(size * 0.3);
      let y = cap.bottom - lines.length * lh;   // plans from before subtitle styles: bottom-aligned
      if (cap.height) {
        const total = lines.length * lh;
        y = cap.valign === 'top' ? cap.top + 8 : cap.valign === 'middle' ? cap.top + (cap.height - total) / 2 : cap.top + cap.height - 8 - total;
      }
      y = Math.max(0, Math.round(y));
      const limit = W * 0.95 - pad * 2;
      for (const line of lines) {
        const full = ctx.measureText(line).width;
        const squeeze = full > limit ? limit / full : 1;   // still too wide: narrow it ourselves (fillText's maxWidth is not reliable for Burmese in every browser)
        const tw = full * squeeze;
        if (st.bg_opacity > 0) {
          ctx.fillStyle = rgba(st.bg, st.bg_opacity);
          ctx.beginPath(); ctx.roundRect((W - tw) / 2 - pad, y + 2, tw + pad * 2, lh - 4, 8); ctx.fill();
        }
        ctx.save(); ctx.translate(W / 2, y + lh / 2); ctx.scale(squeeze, 1);
        if (st.outline) { ctx.lineJoin = 'round'; ctx.lineWidth = Math.max(2, Math.round(size / 11)); ctx.strokeStyle = st.outline; ctx.strokeText(line, 0, 0); }
        ctx.fillStyle = st.color; ctx.fillText(line, 0, 0);
        ctx.restore();
        y += lh;
      }
    }
  };
  // subtitle on top of the logo unless the user swapped the two layers (plan.logo.above)
  if (plan.logo?.above) { drawText(); drawLogo(); } else { drawLogo(); drawText(); }
  comp.uploadOverlay();
}

/** Output time (seconds, before the global speed) -> source time, following the plan's scenes (slow-down, then freeze on the last frame). */
function makeMapper(plan) {
  const scenes = plan.scenes;
  let k = 0;
  return (internal) => {   // monotonic calls only
    while (k < scenes.length - 1 && internal >= scenes[k + 1][3] - 1e-6) k++;
    const [a, b, speed, outStart] = scenes[k];
    return Math.min(a + Math.max(0, internal - outStart) * speed, Math.max(a, b - 0.001));
  };
}

/**
 * Draw the video from the plan. file = the user's original video (still on the phone), audioBlob = the server's finished sound,
 * logoFile = optional logo image. opts: onProgress(0..1, text), signal {aborted}. Returns { blob, stats }.
 */
export async function renderFromPlan(file, plan, audioBlob, logoFile, { onProgress = () => {}, signal = { aborted: false } } = {}) {
  captionFamily = await loadCaptionFont(plan.caption?.style?.font || 'sans');
  const started = performance.now();
  const [W, H] = plan.out;
  if (!(await canEncodeVideo('avc', { width: W, height: H, bitrate: Math.round(W * H * 3.2) }))) throw new Error('This device cannot encode H.264 video');
  const input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
  const vTrack = await input.getPrimaryVideoTrack();
  if (!vTrack) throw new Error('No video track');
  const comp = makeCompositor(plan);
  const logo = logoFile && plan.logo ? await createImageBitmap(logoFile).catch(() => null) : null;

  const output = new Output({ format: new Mp4OutputFormat(), target: new BufferTarget() });
  const fps = Math.max(1, Math.min(plan.fps || 30, 30));
  const vSource = new CanvasSource(comp.canvas, { codec: 'avc', bitrate: Math.round(W * H * 3.2), hardwareAcceleration: 'prefer-hardware' });
  output.addVideoTrack(vSource, { frameRate: fps });

  // the server's sound is copied as it is (AAC packets): no decoding, no encoding, works on phones without an AAC encoder
  const aInput = new Input({ source: new BlobSource(audioBlob), formats: ALL_FORMATS });
  const aTrack = await aInput.getPrimaryAudioTrack();
  if (!aTrack) throw new Error('The voice track has no audio');
  const aSource = new EncodedAudioPacketSource(aTrack.codec);
  output.addAudioTrack(aSource);
  const aConfig = await aTrack.getDecoderConfig();
  await output.start();

  const total = plan.duration, speed = plan.speed || 1, frames = Math.max(1, Math.round(total * fps));
  const map = makeMapper(plan);
  const cues = plan.cues || [], windows = plan.subtitle?.windows;
  let cueIdx = 0, shownText = null, hasOverlay = false;
  const subAt = (t) => !!plan.subtitle && (windows == null || windows.some(([a, b]) => t >= a && t <= b));
  if (logo) { drawOverlay(comp, plan, '', logo); hasOverlay = true; shownText = ''; }

  const srcTimes = [];   // the generator below fills this so each drawn frame knows its source time
  const times = (async function* () {
    for (let i = 0; i < frames; i++) { const s = map((i / fps) * speed); srcTimes.push(s); yield s; }
  }());

  let i = 0, last = null, lastReport = 0;
  const loopStart = performance.now();
  for await (const sample of new VideoSampleSink(vTrack).samplesAtTimestamps(times)) {
    if (signal.aborted) throw new Error('aborted');
    const t = i / fps;
    while (cueIdx < cues.length && cues[cueIdx][1] <= t) cueIdx++;
    const cue = cueIdx < cues.length && cues[cueIdx][0] <= t ? cues[cueIdx][2] : '';
    if (cue !== shownText) {
      drawOverlay(comp, plan, cue, logo);
      shownText = cue; hasOverlay = !!(cue || logo);
    }
    const s = sample || last;
    if (s) comp.draw(s, subAt(srcTimes[i]), hasOverlay);
    await vSource.add(t, 1 / fps);
    if (sample && sample !== last) { last?.close?.(); last = sample; }
    i++;
    if (performance.now() - lastReport > 250) { lastReport = performance.now(); onProgress(0.9 * Math.min(1, i / frames), `Frame ${i}/${frames}`); }
  }
  last?.close?.();
  if (i < frames * 0.9) throw new Error(`The video could not be read completely (${i}/${frames} frames)`);
  const loopSeconds = (performance.now() - loopStart) / 1000;

  const sink = new EncodedPacketSink(aTrack);
  let first = true;
  for await (const packet of sink.packets()) {
    if (signal.aborted) throw new Error('aborted');
    await aSource.add(packet, first ? { decoderConfig: aConfig } : undefined);
    first = false;
  }
  await output.finalize();
  const seconds = (performance.now() - started) / 1000;
  const blob = new Blob([output.target.buffer], { type: 'video/mp4' });
  onProgress(1, 'Done');
  return { blob, stats: { canvas: 'webgl', output: `${W}x${H}`, videoSeconds: +total.toFixed(1), seconds: +seconds.toFixed(1), speed: +(total / seconds).toFixed(2),
    frames: i, videoLoopSeconds: +loopSeconds.toFixed(1), outputMB: +(blob.size / 1048576).toFixed(1) } };
}

/** Quick check shown before offering the button: WebCodecs H.264 encoding + WebGL + a measured encode speed (no AAC encoder needed). */
let capCache = null;
export function deviceCapability() {
  if (capCache) return capCache;
  capCache = (async () => {
    const info = { cores: navigator.hardwareConcurrency || 0, memory: navigator.deviceMemory || 0, ua: navigator.userAgent.slice(0, 160) };
    try {
      if (typeof VideoEncoder === 'undefined' || typeof VideoDecoder === 'undefined') return { ...info, ok: false, reason: 'no WebCodecs' };
      const gl = document.createElement('canvas').getContext('webgl');
      if (!gl) return { ...info, ok: false, reason: 'no WebGL' };
      if (!(await canEncodeVideo('avc', { width: 720, height: 1280, bitrate: 3_000_000 }))) return { ...info, ok: false, reason: 'no H.264 encoder' };
      const { capabilityTest } = await import('./deviceRender.js');
      const r = await capabilityTest(720);
      return { ...info, ok: !!r.ok, fps: r.fps, reason: r.reason || '' };
    } catch (e) { return { ...info, ok: false, reason: String(e.message || e).slice(0, 100) }; }
  })();
  return capCache;
}
