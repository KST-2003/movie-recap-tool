import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n.jsx';

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

export default function PreviewStudio({ src, logoFile, fx, onChange }) {
  const { tr } = useI18n();
  const stageRef = useRef(null);
  const videoRef = useRef(null);
  const bgRef = useRef(null);
  const [logoUrl, setLogoUrl] = useState('');
  const [logoAspect, setLogoAspect] = useState(1); // natural height / width
  const [dims, setDims] = useState({ w: 16, h: 9 });
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [looping, setLooping] = useState(false);
  const loopStart = useRef(0);
  const scrubbing = useRef(false); // finger/mouse is on the seek bar: ignore playback time updates

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
    <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{tr('Preview before generating')}</h3>
        <span className="text-xs text-slate-500">{fx.aspect === 'original' ? '' : `${fx.aspect} · ${fw}×${fh} · `}{tr('Colours are approximate')}</span>
      </div>

      <div className="flex justify-center">
        <div
          ref={stageRef}
          style={{ aspectRatio: `${fw} / ${fh}`, width: portraitish ? `min(100%, calc(70vh * ${fw / fh}))` : '100%' }}
          className="relative max-w-3xl select-none touch-none overflow-hidden rounded-xl border border-slate-800 bg-black"
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
              onLoadedMetadata={(e) => {
                setDims({ w: e.target.videoWidth || 16, h: e.target.videoHeight || 9 });
                setDuration(e.target.duration || 0);
                e.target.playbackRate = fx.videoSpeed;
              }}
              onTimeUpdate={(e) => { if (!scrubbing.current) setTime(e.target.currentTime); syncBg(e); }}
              onSeeked={syncBg}
              onPlay={syncBg}
              onPause={(e) => { setLooping(false); syncBg(e); }}
              style={cropFit ? { objectPosition: `${fx.panX * 100}% ${fx.panY * 100}%` } : undefined}
              className={`absolute inset-0 w-full h-full pointer-events-none ${cropFit ? 'object-cover' : 'object-contain'}`}
            />
          </div>
          {fx.blurBoxes.map((b, i) => (
            <div
              key={i}
              onPointerDown={(e) => dragBox(e, i)}
              style={{
                left: `${b.x * 100}%`, top: `${b.y * 100}%`, width: `${b.w * 100}%`, height: `${b.h * 100}%`,
                backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
              }}
              className="absolute border border-dashed border-purple-300 cursor-move"
            >
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => onChange({ blurBoxes: fx.blurBoxes.filter((_, k) => k !== i) })}
                className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-600 text-white text-xs leading-5"
              >×</button>
              <div onPointerDown={(e) => resizeBox(e, i)} className="absolute -bottom-2 -right-2 w-5 h-5 rounded-full bg-purple-500 border-2 border-white cursor-nwse-resize" />
            </div>
          ))}
          {logoUrl && (
            <div
              onPointerDown={dragLogo}
              style={{ left: `${lx * 100}%`, top: `${ly * 100}%`, width: `${lw * 100}%` }}
              className="absolute cursor-move ring-1 ring-purple-300/70"
            >
              <img
                src={logoUrl}
                alt=""
                draggable={false}
                onLoad={(e) => setLogoAspect((e.target.naturalHeight || 1) / (e.target.naturalWidth || 1))}
                className="w-full block pointer-events-none"
              />
              <div onPointerDown={resizeLogo} className="absolute -bottom-2 -right-2 w-5 h-5 rounded-full bg-purple-500 border-2 border-white cursor-nwse-resize" />
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="range" min={0} max={duration || 1} step={0.1} value={time}
          onPointerDown={() => { scrubbing.current = true; }}
          onPointerUp={() => { scrubbing.current = false; }}
          onPointerCancel={() => { scrubbing.current = false; }}
          onChange={(e) => {
            const t = Number(e.target.value);
            loopStart.current = t;   // while the 5 s loop plays, the window moves to where you drag
            if (videoRef.current) videoRef.current.currentTime = t;
            setTime(t);
          }}
          className="flex-1 accent-purple-500"
        />
        <span className="text-xs text-slate-400 shrink-0 min-w-[6.5rem] whitespace-nowrap tabular-nums text-right">{time.toFixed(1)} / {duration.toFixed(0)}s</span>
      </div>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={looping ? stop : playWindow} className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-sm text-white">
          {looping ? tr('■ Stop') : tr('▶ Play 5 s (loop)')}
        </button>
        <button
          type="button"
          disabled={fx.blurBoxes.length >= 6}
          onClick={() => onChange({ blurBoxes: [...fx.blurBoxes, { x: 0.1, y: 0.75, w: 0.8, h: 0.12 }] })}
          className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-200 disabled:opacity-40"
        >{tr('+ Blur box')}</button>
        {fx.logoXY && (
          <button type="button" onClick={() => onChange({ logoXY: null })} className="px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-200">
            {tr('Reset logo position')}
          </button>
        )}
      </div>
      <p className="text-xs text-slate-500">
        {tr('Drag the logo or a blur box to move it; drag its round corner (or use the Logo size slider) to resize. Automatic blur of the original subtitles and watermark is still added when you generate.')}
        {cropFit && ` ${tr('Drag the picture to choose which part stays in the frame.')}`}
      </p>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        {SLIDERS.map(([label, key, min, max, step]) => (
          <label key={key} className="text-xs text-slate-400">
            {tr(label)}: <span className="text-slate-200">{Number(fx[key]).toFixed(2)}</span>
            <input
              type="range" min={min} max={max} step={step} value={fx[key]}
              onChange={(e) => onChange({ [key]: Number(e.target.value) })}
              className="w-full accent-purple-500"
            />
          </label>
        ))}
        <label className="text-xs text-slate-400">
          {tr('Logo position')}
          <select
            value={fx.logoPosition}
            onChange={(e) => onChange({ logoPosition: e.target.value, logoXY: null })}
            className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg p-1.5 text-slate-200"
          >
            {['top-right', 'top-left', 'bottom-right', 'bottom-left', 'center'].map((p) => (
              <option key={p} value={p}>{tr(p)}</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
