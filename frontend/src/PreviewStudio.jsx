import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n.jsx';

// Live preview of the chosen video BEFORE generating: grading, speed, flip, a draggable logo and draggable blur boxes.
// CSS filters only approximate ffmpeg's eq filter, so tones can differ slightly in the final file.
// Blur boxes are kept in DISPLAYED coordinates; App converts them to source coordinates (flip) when it submits.

const LOOP_SECONDS = 5;
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const SLIDERS = [
  ['Video speed', 'videoSpeed', 0.5, 2, 0.05],
  ['Brightness', 'brightness', -0.5, 0.5, 0.05],
  ['Contrast', 'contrast', 0.5, 1.5, 0.05],
  ['Saturation', 'saturation', 0, 2, 0.05],
  ['Logo size', 'logoSize', 0.05, 0.5, 0.01],
];

export default function PreviewStudio({ src, logoFile, fx, onChange }) {
  const { tr } = useI18n();
  const stageRef = useRef(null);
  const videoRef = useRef(null);
  const [logoUrl, setLogoUrl] = useState('');
  const [logoAspect, setLogoAspect] = useState(1); // natural height / width
  const [dims, setDims] = useState({ w: 16, h: 9 });
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [looping, setLooping] = useState(false);
  const loopStart = useRef(0);

  useEffect(() => {
    if (!logoFile) { setLogoUrl(''); return undefined; }
    const url = URL.createObjectURL(logoFile);
    setLogoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [logoFile]);

  useEffect(() => { if (videoRef.current) videoRef.current.playbackRate = fx.videoSpeed; }, [fx.videoSpeed, src]);

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
  const lh = lw * (dims.w / dims.h) * logoAspect;
  const mx = 30 / dims.w;
  const my = 30 / dims.h;
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
    const move = (ev) => onMove((ev.clientX - sx) / rect.width, (ev.clientY - sy) / rect.height);
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const dragLogo = (e) => {
    const [x0, y0] = [lx, ly];
    drag(e, (dx, dy) => onChange({ logoXY: [clamp(x0 + dx, 0, 1 - lw), clamp(y0 + dy, 0, 1 - lh)] }));
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

  const filter = `brightness(${1 + fx.brightness}) contrast(${fx.contrast}) saturate(${fx.saturation})`;

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{tr('Preview before generating')}</h3>
        <span className="text-xs text-slate-500">{tr('Colours are approximate')}</span>
      </div>

      <div className="flex justify-center">
        <div ref={stageRef} className="relative w-full max-w-xs select-none touch-none overflow-hidden rounded-xl border border-slate-800">
          <video
            ref={videoRef}
            src={src}
            playsInline
            onLoadedMetadata={(e) => {
              setDims({ w: e.target.videoWidth || 16, h: e.target.videoHeight || 9 });
              setDuration(e.target.duration || 0);
              e.target.playbackRate = fx.videoSpeed;
            }}
            onTimeUpdate={(e) => setTime(e.target.currentTime)}
            onPause={() => setLooping(false)}
            style={{ filter, transform: fx.flip ? 'scaleX(-1)' : 'none' }}
            className="w-full block"
          />
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
            <img
              src={logoUrl}
              alt=""
              draggable={false}
              onLoad={(e) => setLogoAspect((e.target.naturalHeight || 1) / (e.target.naturalWidth || 1))}
              onPointerDown={dragLogo}
              style={{ left: `${lx * 100}%`, top: `${ly * 100}%`, width: `${lw * 100}%` }}
              className="absolute cursor-move ring-1 ring-purple-300/70"
            />
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="range" min={0} max={duration || 1} step={0.1} value={time}
          onChange={(e) => { const t = Number(e.target.value); if (videoRef.current) videoRef.current.currentTime = t; setTime(t); }}
          className="flex-1 accent-purple-500"
        />
        <span className="text-xs text-slate-400 w-16 text-right">{time.toFixed(1)} / {duration.toFixed(0)}s</span>
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
        {tr('Drag the logo or a blur box to move it; drag the round corner to resize. Automatic blur of the original subtitles and watermark is still added when you generate.')}
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
