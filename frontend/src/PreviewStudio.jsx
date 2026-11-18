import Select from './Select.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n.jsx';
import { rgba } from './captionFonts.js';
import { SAMPLE, useCaptionFamily } from './CaptionStyleControls.jsx';

// Live preview of the chosen video BEFORE generating, inside the chosen output frame (9:16, 1:1, ...), like CapCut:
// reframe (fit over blurred copy, or crop + drag to pan), grading, speed, flip, draggable logo and blur boxes.
// Logo and blur boxes live in the OUTPUT frame (displayed coordinates), the render applies them after reframe + flip.
// CSS filters only approximate ffmpeg's eq filter, so tones can differ slightly in the final file.

const LOOP_SECONDS = 5;
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
export const ASPECTS = { '9:16': [9, 16], '1:1': [1, 1], '4:5': [4, 5], '16:9': [16, 9] };
const SLIDERS = [
  ['Video speed', 'videoSpeed', 0.5, 2, 0.05],
  ['Brightness', 'brightness', -0.5, 0.5, 0.05],
  ['Contrast', 'contrast', 0.5, 1.5, 0.05],
  ['Saturation', 'saturation', 0, 2, 0.05],
  ['Logo size', 'logoSize', 0.05, 0.5, 0.01],
];

// Same rule as backend pipeline._out_size: short side = min(1080, source short side).
export function frameSize(aspect, src) {
  if (!ASPECTS[aspect]) return [src.w, src.h];
  const [a, b] = ASPECTS[aspect];
  const short = Math.floor(Math.max(360, Math.min(1080, Math.min(src.w, src.h))) / 2) * 2;
  return a <= b ? [short, Math.round((short * b) / a)] : [Math.round((short * a) / b), short];
}

// simple = the preset builder: only what a preset stores (format, grading, speed, flip, subtitle sample); no logo file, blur boxes or layers.
export default function PreviewStudio({ src, logoFile, fx, onChange, simple = false }) {
  const { tr } = useI18n();
  const stageRef = useRef(null);
  const cap = fx.captionStyle;   // subtitle style chosen before generating: a sample line is drawn in the frame
  const capFamily = useCaptionFamily(cap?.font || 'sans');
  const videoRef = useRef(null);
  const bgRef = useRef(null);
  const [logoUrl, setLogoUrl] = useState('');
  const [logoAspect, setLogoAspect] = useState(1); // natural height / width
  const [dims, setDims] = useState({ w: 16, h: 9 });
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [looping, setLooping] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const loopStart = useRef(0);
  const scrubbing = useRef(false); // finger/mouse is on the seek bar: ignore playback time updates
  // Dragging the bar fires dozens of seeks a second. Safari on a Mac copes, a phone's decoder does not (every new seek cancels the
  // one before, so the picture freezes until you let go). So only ONE seek runs at a time: while it is busy the latest target waits,
  // and when it finishes ("seeked") the newest target is sought, so the picture keeps following the finger.
  const lastInput = useRef(0);       // when the bar last changed by the user: the picture's own time updates must not pull the thumb back for a moment
  const lastTarget = useRef(null);   // the time the bar was last dragged to
  const seekBusy = useRef(false);
  const seekWanted = useRef(null);
  const seekTimer = useRef(null);
  const seekNow = () => {
    const v = videoRef.current;
    if (!v || seekWanted.current == null) return;
    const t = seekWanted.current;
    seekWanted.current = null;
    if (Math.abs(v.currentTime - t) < 0.01) return;   // already there: no "seeked" event would come
    seekBusy.current = true;
    v.currentTime = t;   // (fastSeek was tried: on iPhone Safari it can land on the same keyframe, no "seeked" event, and the picture never moved)
    clearTimeout(seekTimer.current);
    // Safety: some browsers never send "seeked" for a seek that was replaced; do not wait for it longer than this.
    seekTimer.current = setTimeout(() => { seekBusy.current = false; if (seekWanted.current != null) seekNow(); }, 1500);   // a phone's HEVC clip can need > 350 ms: re-sending earlier cancelled every seek and the picture never landed
  };
  const seekTo = (t) => { seekWanted.current = t; if (!seekBusy.current) seekNow(); };
  // iOS web views (the phone app) load NO picture data for a paused video (readyState stays 1): a seek then never finishes ("seeking 1" forever, seen with a
  // 4K clip) and "Play 5 s" works only because playing makes iOS load. So on a touch release we start playing MUTED right away, together with the seek,
  // and pause again shortly after the seek has landed.
  const kicking = useRef(null);   // { wasMuted, timer } while a muted kick-play is running
  const endKick = () => {
    const k = kicking.current, v = videoRef.current;
    if (!k) return;
    clearTimeout(k.timer);
    kicking.current = null;
    if (v) { try { v.pause(); } catch { /* ignore */ } v.muted = k.wasMuted; }
  };
  const holdKick = () => { const k = kicking.current; if (k) { clearTimeout(k.timer); k.timer = setTimeout(endKick, 4000); } };   // a long drag keeps it alive
  const startKick = (v) => {
    if (kicking.current || !v.paused) return;
    const wasMuted = v.muted;
    v.muted = true;
    kicking.current = { wasMuted, timer: setTimeout(endKick, 4000) };   // safety: never leave it playing
    let pr;
    try { pr = v.play(); } catch { endKick(); return; }
    if (pr && pr.catch) pr.catch(() => endKick());
  };
  const onSeeked = (e) => {
    clearTimeout(seekTimer.current);
    seekBusy.current = false;
    if (seekWanted.current != null) { seekNow(); return; }
    if (kicking.current && !scrubbing.current) { clearTimeout(kicking.current.timer); kicking.current.timer = setTimeout(endKick, 120); }   // not while the finger is still down: it keeps playing for the whole drag   // landed: let one frame draw, then pause
    syncBg(e);   // the blurred background is only moved when the main picture has settled
  };

  const finishScrub = () => {
    if (!scrubbing.current) return;
    scrubbing.current = false;
    const v = videoRef.current;
    if (v && lastTarget.current != null) { seekWanted.current = null; const touch = typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches; if (touch && !looping) startKick(v); v.currentTime = lastTarget.current; if (kicking.current) { clearTimeout(kicking.current.timer); kicking.current.timer = setTimeout(endKick, 700); } /* normally ended sooner by the seeked event */ }
  };
  useEffect(() => {
    const evs = ['pointerup', 'pointercancel', 'touchend', 'touchcancel', 'mouseup', 'blur'];
    evs.forEach((n) => window.addEventListener(n, finishScrub));
    return () => evs.forEach((n) => window.removeEventListener(n, finishScrub));
  }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  // A video can report an unknown length (Infinity / NaN) until it is read further: the bar then had no usable range.
  const readDuration = (v) => {
    let d = v.duration;
    if (!Number.isFinite(d) || d <= 0) { try { d = v.seekable.length ? v.seekable.end(v.seekable.length - 1) : 0; } catch { d = 0; } }
    setDuration(Number.isFinite(d) ? d : 0);
  };

  const moveBar = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    if (!r.width || !duration) return;
    const t = Math.min(duration, Math.max(0, ((e.clientX - r.left) / r.width) * duration));
    lastInput.current = Date.now();
    lastTarget.current = t;
    loopStart.current = t;   // while the 5 s loop plays, the window moves to where you drag
    // Live scrubbing everywhere. On touch screens the video is kept playing (muted) while the finger is down, because iOS loads picture data only
    // for a playing video; seeks still go one at a time (seekTo waits for "seeked"), so they do not cancel each other.
    const touch = e.pointerType === 'touch' || e.pointerType === 'pen';
    if (touch && videoRef.current) { startKick(videoRef.current); holdKick(); }
    seekTo(t);
    setTime(t);
  };
  // hidden readout (tap the time 3 times): what the video does, for support screenshots
  const [dbg, setDbg] = useState(false);
  const dbgTaps = useRef([]);
  const dbgText = () => { const v = videoRef.current; return v ? `t ${v.currentTime.toFixed(2)} target ${lastTarget.current == null ? '-' : lastTarget.current.toFixed(2)} ready ${v.readyState} net ${v.networkState} seeking ${v.seeking ? 1 : 0} paused ${v.paused ? 1 : 0} err ${v.error ? v.error.code : 0} dur ${Number.isFinite(v.duration) ? v.duration.toFixed(1) : v.duration} ${v.videoWidth}x${v.videoHeight}` : 'no video'; };
  const [dbgLine, setDbgLine] = useState('');
  useEffect(() => { if (!dbg) return undefined; const id = setInterval(() => setDbgLine(dbgText()), 300); return () => clearInterval(id); }, [dbg]);   // eslint-disable-line react-hooks/exhaustive-deps

  const [fw, fh] = frameSize(fx.aspect, dims);   // output frame in pixels
  const reframed = fx.aspect !== 'original' && Math.abs(fw / fh - dims.w / dims.h) > 0.01;
  const blurFit = reframed && fx.fitMode === 'blur';
  const cropFit = reframed && fx.fitMode === 'crop';

  useEffect(() => {
    if (!logoFile) { setLogoUrl(''); return undefined; }
    const url = URL.createObjectURL(logoFile);
    setLogoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [logoFile]);

  useEffect(() => {
    [videoRef.current, bgRef.current].forEach((v) => { if (v) v.playbackRate = fx.videoSpeed; });
  }, [fx.videoSpeed, src, blurFit]);

  // The blurred background is a second muted video that follows the main one.
  const syncBg = (e) => {
    const bg = bgRef.current;
    if (!bg) return;
    const v = e.target;
    if (scrubbing.current) return;   // while dragging, only the main picture moves (two seeking videos = a stuck picture on a phone)
    if (Math.abs(bg.currentTime - v.currentTime) > 0.2) bg.currentTime = v.currentTime;
    if (v.paused !== bg.paused) { if (v.paused) bg.pause(); else bg.play().catch(() => {}); }
  };

  // Play a 5 s window over and over (requestAnimationFrame: timeupdate is too coarse).
  useEffect(() => {
    if (!looping) return undefined;
    let raf;
    const tick = () => {
      const v = videoRef.current;
      if (v && v.currentTime >= loopStart.current + LOOP_SECONDS) v.currentTime = loopStart.current;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [looping]);

  const playWindow = () => {
    const v = videoRef.current;
    if (!v) return;
    loopStart.current = v.currentTime;
    v.playbackRate = fx.videoSpeed;
    setLooping(true);
    v.play();
  };
  const stop = () => { setLooping(false); videoRef.current?.pause(); };

  // Logo box in frame fractions: dragged position, else the preset corner (30 px margin like the render).
  const lw = fx.logoSize;
  const lh = lw * (fw / fh) * logoAspect;
  const mx = 30 / fw;
  const my = 30 / fh;
  const preset = {
    'top-right': [1 - lw - mx, my], 'top-left': [mx, my],
    'bottom-right': [1 - lw - mx, 1 - lh - my], 'bottom-left': [mx, 1 - lh - my],
    center: [(1 - lw) / 2, (1 - lh) / 2],
  }[fx.logoPosition] || [1 - lw - mx, my];
  const [lx, ly] = fx.logoXY || preset;

  // Generic drag: fractions of the stage, relative to where the pointer went down.
  const drag = (e, onMove) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = stageRef.current.getBoundingClientRect();
    const sx = e.clientX;
    const sy = e.clientY;
    const move = (ev) => onMove((ev.clientX - sx) / rect.width, (ev.clientY - sy) / rect.height, rect);
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  // Drag the sample subtitle up / down: the style becomes "custom" with y = height of the subtitle's middle (fraction of the frame).
  const dragCaption = (e) => {
    const stage = stageRef.current.getBoundingClientRect(), box = e.currentTarget.getBoundingClientRect();
    const y0 = (box.top + box.height / 2 - stage.top) / stage.height;
    drag(e, (dx, dy) => onChange({ captionStyle: { ...cap, position: 'custom', y: Math.round(clamp(y0 + dy, 0.05, 0.95) * 1000) / 1000 } }));
  };
  const dragLogo = (e) => {
    const [x0, y0] = [lx, ly];
    drag(e, (dx, dy) => onChange({ logoXY: [clamp(x0 + dx, 0, 1 - lw), clamp(y0 + dy, 0, 1 - lh)] }));
  };
  const resizeLogo = (e) => {
    const w0 = lw;
    const [x0, y0] = [lx, ly];
    onChange({ logoXY: [x0, y0] }); // keep the top-left corner fixed while resizing
    drag(e, (dx) => onChange({ logoSize: clamp(w0 + dx, 0.05, Math.min(0.5, 1 - x0)) }));
  };
  const setBox = (i, patch) => onChange({ blurBoxes: fx.blurBoxes.map((b, k) => (k === i ? { ...b, ...patch } : b)) });
  const dragBox = (e, i) => {
    const b = fx.blurBoxes[i];
    drag(e, (dx, dy) => setBox(i, { x: clamp(b.x + dx, 0, 1 - b.w), y: clamp(b.y + dy, 0, 1 - b.h) }));
  };
  const resizeBox = (e, i) => {
    const b = fx.blurBoxes[i];
    drag(e, (dx, dy) => setBox(i, { w: clamp(b.w + dx, 0.04, 1 - b.x), h: clamp(b.h + dy, 0.03, 1 - b.y) }));
  };

  // Crop mode: drag the picture to choose which part stays in the frame.
  const dragPan = (e) => {
    if (!cropFit) return;
    const [p0x, p0y] = [fx.panX, fx.panY];
    const wider = dims.w / dims.h > fw / fh;   // picture overflows sideways (else up/down), in stage fractions
    const overflow = wider ? (dims.w / dims.h) / (fw / fh) - 1 : (fw / fh) / (dims.w / dims.h) - 1;
    drag(e, (dx, dy) => (wider
      ? onChange({ panX: clamp(p0x - dx / overflow, 0, 1) })
      : onChange({ panY: clamp(p0y - dy / overflow, 0, 1) })));
  };

  const filter = `brightness(${1 + fx.brightness}) contrast(${fx.contrast}) saturate(${fx.saturation})`;
  const portraitish = fh >= fw;

  return (
    <div className="rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">{tr('Preview before generating')}</h3>
        <span className="text-xs text-ink-faint">{fx.aspect === 'original' ? '' : `${fx.aspect} · ${fw}×${fh} · `}{tr('Colours are approximate')}</span>
      </div>

      <div className="flex justify-center">
        <div
          ref={stageRef}
          style={{ aspectRatio: `${fw} / ${fh}`, width: portraitish ? `min(100%, calc(70vh * ${fw / fh}))` : '100%', containerType: 'inline-size' }}
          className="relative max-w-3xl select-none touch-none overflow-hidden rounded-2xl border border-violet-100 bg-black text-white"
        >
          <div
            onPointerDown={dragPan}
            style={{ filter, transform: fx.flip ? 'scaleX(-1)' : 'none', cursor: cropFit ? 'grab' : 'default' }}
            className="absolute inset-0"
          >
            {blurFit && (
              <video
                ref={bgRef}
                src={src}
                muted
                playsInline
                style={{ filter: 'blur(22px)', transform: 'scale(1.15)' }}
                className="absolute inset-0 w-full h-full object-cover pointer-events-none"
              />
            )}
            <video
              ref={videoRef}
              src={src}
              playsInline
              preload="auto"
              onLoadedMetadata={(e) => {
                setDims({ w: e.target.videoWidth || 16, h: e.target.videoHeight || 9 });
                readDuration(e.target);
                e.target.playbackRate = fx.videoSpeed;
              }}
              onDurationChange={(e) => readDuration(e.target)}
              onTimeUpdate={(e) => {
                const busy = scrubbing.current || seekBusy.current || seekWanted.current != null || Date.now() - lastInput.current < 600;
                if (!busy) setTime(e.target.currentTime);
                syncBg(e);
              }}
              onSeeked={onSeeked}
              onPlay={syncBg}
              onPause={(e) => { setLooping(false); syncBg(e); }}
              style={cropFit ? { objectPosition: `${fx.panX * 100}% ${fx.panY * 100}%` } : undefined}
              className={`absolute inset-0 w-full h-full pointer-events-none ${cropFit ? 'object-cover' : 'object-contain'}`}
            />
          </div>
          {/* Drawn in the SAME order as the finished video: blur boxes at the bottom, then the logo, the subtitle always on top
              (recap_engine: manual blur -> logo -> captions). The sample subtitle was once drawn UNDER the blur boxes here, which
              made it look as if a blur box would cover the subtitle: it never does. */}
          {fx.blurBoxes.map((b, i) => (
            <div
              key={i}
              onPointerDown={(e) => dragBox(e, i)}
              style={{
                left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%`,
                backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
              }}
              className="absolute border border-dashed border-violet-300 cursor-move"
            >
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => onChange({ blurBoxes: fx.blurBoxes.filter((_, k) => k !== i) })}
                className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-600 text-white text-xs leading-5"
              >×</button>
              <div onPointerDown={(e) => resizeBox(e, i)} className="absolute -bottom-2 -right-2 w-5 h-5 rounded-full bg-violet-500 border-2 border-white cursor-nwse-resize text-white" />
            </div>
          ))}
          {logoUrl && (
            <div
              onPointerDown={dragLogo}
              style={{ left: `${lx * 100}%`, top: `${ly * 100}%`, width: `${lw * 100}%`, zIndex: fx.logoOnTop ? 2 : undefined }}
              className="absolute cursor-move ring-1 ring-violet-300/70"
            >
              <img
                src={logoUrl}
                alt=""
                draggable={false}
                onLoad={(e) => setLogoAspect((e.target.naturalHeight || 1) / (e.target.naturalWidth || 1))}
                className="w-full block pointer-events-none"
              />
              <div onPointerDown={resizeLogo} className="absolute -bottom-2 -right-2 w-5 h-5 rounded-full bg-violet-500 border-2 border-white cursor-nwse-resize text-white" />
              <button type="button" aria-label={tr('Remove logo')} onPointerDown={(e) => e.stopPropagation()} onClick={() => onChange({ removeLogo: true })}
                className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 border-2 border-white text-white text-xs leading-none flex items-center justify-center">×</button>
            </div>
          )}
          {cap && (   /* sample subtitle in the chosen style; same rules as the render: 5% of the width x size, strip at top / middle / bottom */
            <div className="absolute inset-x-0 flex justify-center px-[6%] pointer-events-none"
              style={cap.position === 'custom' ? { top: `${cap.y * 100}%`, transform: 'translateY(-50%)' }
                : cap.position === 'top' ? { top: '5%' } : cap.position === 'middle' ? { top: '50%', transform: 'translateY(-50%)' } : { bottom: '4%' }}>
              <span onPointerDown={dragCaption} title={tr('Drag up or down to place the subtitle')} className="pointer-events-auto cursor-grab active:cursor-grabbing touch-none" style={{
                fontFamily: capFamily, fontWeight: cap.font === 'sans-regular' ? 400 : 700, fontSize: `${(5 * cap.size).toFixed(2)}cqw`, lineHeight: 1.75,
                color: cap.color, background: cap.bg_opacity > 0 ? rgba(cap.bg, cap.bg_opacity) : 'transparent', borderRadius: '0.4em', padding: '0 0.5em',
                WebkitTextStroke: cap.outline ? `${(5 * cap.size / 11).toFixed(2)}cqw ${cap.outline}` : '0', paintOrder: 'stroke fill', textAlign: 'center',
              }}>{SAMPLE}</span>
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Our own slider (the phone app's web view did not seek with the native range input). Pointer capture keeps the drag even outside the bar. */}
        <div
          role="slider" tabIndex={0} aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(time)} aria-label={tr('Position in the video')}
          className="relative flex-1 h-9 cursor-pointer select-none"
          style={{ touchAction: 'none' }}
          onPointerDown={(e) => { try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* not capturable (synthetic / odd web view): the window listeners still end the drag */ } scrubbing.current = true; moveBar(e); }}
          onPointerMove={(e) => { if (scrubbing.current) moveBar(e); }}
          onPointerUp={finishScrub}
          onPointerCancel={finishScrub}
          onLostPointerCapture={finishScrub}
          onKeyDown={(e) => {
            const step = e.shiftKey ? 5 : 1;
            if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); const t = Math.min(duration, Math.max(0, time + (e.key === 'ArrowRight' ? step : -step))); lastInput.current = Date.now(); lastTarget.current = t; loopStart.current = t; seekTo(t); setTime(t); }
          }}
        >
          <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-violet-100" />
          <div className="absolute left-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-violet-500" style={{ width: `${duration ? Math.min(100, (time / duration) * 100) : 0}%` }} />
          <div className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-500 shadow-card ring-4 ring-white" style={{ left: `${duration ? Math.min(100, (time / duration) * 100) : 0}%` }} />
        </div>
        <span onClick={() => { const n = Date.now(); dbgTaps.current = [...dbgTaps.current.filter((x) => n - x < 1500), n]; if (dbgTaps.current.length >= 3) { dbgTaps.current = []; setDbg((d) => !d); } }}
          className="text-xs text-ink-soft shrink-0 min-w-[6.5rem] whitespace-nowrap tabular-nums text-right select-none">{time.toFixed(1)} / {duration.toFixed(0)}s</span>
      </div>
      {dbg && <p className="break-all rounded-lg bg-ink px-2 py-1 font-mono text-[10px] leading-tight text-white">{dbgLine}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={looping ? stop : playWindow} className="px-3 py-1.5 rounded-lg bg-violet-500 hover:bg-violet-600 text-sm text-white">
          {looping ? tr('■ Stop') : tr('▶ Play 5 s (loop)')}
        </button>
        {!simple && <button
          type="button"
          disabled={fx.blurBoxes.length >= 6}
          onClick={() => onChange({ blurBoxes: [...fx.blurBoxes, { x: 0.1, y: 0.75, w: 0.8, h: 0.12 }] })}
          className="px-3 py-1.5 rounded-lg bg-violet-100 hover:bg-violet-200 text-sm text-ink disabled:opacity-40"
        >{tr('+ Blur box')}</button>}
        {!simple && <div className="relative">
          <button type="button" onClick={() => setLayersOpen((o) => !o)} aria-expanded={layersOpen} title={tr('Layers')}
            className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1.5 ${layersOpen ? 'bg-violet-500 text-white' : 'bg-violet-100 hover:bg-violet-200 text-ink'}`}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12 3 2 8l10 5 10-5-10-5Z" /><path d="m2 12 10 5 10-5" /><path d="m2 16 10 5 10-5" />
            </svg>
            {tr('Layers')}
          </button>
          {layersOpen && (
            <div className="absolute z-20 left-0 bottom-full mb-2 w-64 max-w-[80vw] rounded-2xl border border-violet-200 bg-white p-3 shadow-xl text-xs text-ink-soft space-y-2">
              <p className="text-ink-soft">{tr('Top to bottom, as in the finished video')}</p>
              <ol className="space-y-1">
                {(fx.logoOnTop ? ['Logo', 'Subtitle'] : ['Subtitle', 'Logo']).concat(['Blur boxes', 'Video']).map((name, i) => (
                  <li key={name} className="flex items-center gap-2 rounded-lg bg-violet-50 px-2 py-1.5">
                    <span className="w-4 text-ink-faint">{i + 1}</span><span className="text-ink">{tr(name)}</span>
                  </li>
                ))}
              </ol>
              <label className={`flex items-center gap-2 pt-1 ${logoUrl ? 'cursor-pointer' : 'opacity-50'}`}>
                <input type="checkbox" disabled={!logoUrl} checked={!!fx.logoOnTop} onChange={(e) => onChange({ logoOnTop: e.target.checked })} className="w-4 h-4 accent-violet-500" />
                {tr('Logo above subtitle')}
              </label>
              {!logoUrl && <p className="text-ink-faint">{tr('Upload a logo to change this.')}</p>}
            </div>
          )}
        </div>}
        {fx.logoXY && (
          <button type="button" onClick={() => onChange({ logoXY: null })} className="px-3 py-1.5 rounded-lg bg-violet-100 hover:bg-violet-200 text-sm text-ink">
            {tr('Reset logo position')}
          </button>
        )}
      </div>
      {!simple && <p className="text-xs text-ink-faint">
        {tr('Drag the logo or a blur box to move it; drag its round corner (or use the Logo size slider) to resize. Automatic blur of the original subtitles and watermark is still added when you generate.')}
        {cropFit && ` ${tr('Drag the picture to choose which part stays in the frame.')}`}
      </p>}
      {simple && cropFit && <p className="text-xs text-ink-faint">{tr('Drag the picture to choose which part stays in the frame.')}</p>}

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {SLIDERS.filter(([, key]) => !simple || key !== 'logoSize').map(([label, key, min, max, step]) => (
          <label key={key} className="text-xs text-ink-soft">
            {tr(label)}: <span className="text-ink">{Number(fx[key]).toFixed(2)}</span>
            <input
              type="range" min={min} max={max} step={step} value={fx[key]}
              onChange={(e) => onChange({ [key]: Number(e.target.value) })}
              className="w-full accent-violet-500"
            />
          </label>
        ))}
        {!simple && <label className="text-xs text-ink-soft">
          {tr('Logo position')}
          <Select size="sm" className="mt-1 w-full" value={fx.logoPosition} onChange={(v) => onChange({ logoPosition: v, logoXY: null })}
            options={['top-right', 'top-left', 'bottom-right', 'bottom-left', 'center'].map((p) => ({ value: p, label: tr(p) }))} />
        </label>}
      </div>
    </div>
  );
}
