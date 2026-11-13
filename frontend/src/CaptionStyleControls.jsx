import React, { useEffect, useState } from 'react';
import { useI18n } from './i18n.jsx';
import { CAPTION_FONTS, CAPTION_PRESETS, DEFAULT_CAPTION_STYLE, loadCaptionFont, rgba } from './captionFonts.js';

// Subtitle style controls (font, size, colours, box, outline, position) with a live sample line. Used BEFORE generating (upload
// form, next to the preview) and in the editor after a video is made; the style object is what the server's caption_style takes.
export const SAMPLE = 'မြန်မာစာတန်းထိုး နမူနာ';

export function useCaptionFamily(fontId) {
  const [family, setFamily] = useState('sans-serif');
  useEffect(() => { let on = true; loadCaptionFont(fontId).then((f) => on && setFamily(f)); return () => { on = false; }; }, [fontId]);
  return family;
}

export default function CaptionStyleControls({ cap, onChange, sampleText, showSample = true }) {
  const { tr } = useI18n();
  const capFamily = useCaptionFamily(cap.font);
  const set = (patch) => onChange({ ...cap, ...patch });
  return (
            <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-2.5 space-y-2">
              <p className="text-xs font-semibold text-slate-200">{tr('Subtitle style')}</p>
              {showSample && (
              <div className="rounded-lg overflow-hidden h-20 flex items-center justify-center px-2"
                style={{ background: 'linear-gradient(135deg,#334155 0%,#64748b 45%,#1e293b 100%)' }}>
                <span style={{
                  fontFamily: capFamily, fontWeight: cap.font === 'sans-regular' ? 400 : 700, fontSize: `${Math.round(18 * cap.size)}px`, lineHeight: 1.75,
                  color: cap.color, background: cap.bg_opacity > 0 ? rgba(cap.bg, cap.bg_opacity) : 'transparent', borderRadius: 8, padding: '0 10px',
                  WebkitTextStroke: cap.outline ? `${Math.max(1, Math.round(18 * cap.size / 11))}px ${cap.outline}` : '0', paintOrder: 'stroke fill',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'clip', maxWidth: '100%',
                }}>{sampleText || SAMPLE}</span>
              </div>
              )}
              <div className="flex flex-wrap gap-1.5">
                {CAPTION_PRESETS.map((pr) => (
                  <button key={pr.label} type="button" onClick={() => set(pr.style)}
                    className="px-2 py-1 rounded-lg border border-slate-700 hover:border-purple-400 text-xs"
                    style={{ color: pr.style.color, background: pr.style.bg_opacity > 0 ? rgba(pr.style.bg, Math.max(pr.style.bg_opacity, 0.5)) : '#475569' }}>
                    {tr(pr.label)}
                  </button>
                ))}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs text-slate-400">
                <label className="block">{tr('Font')}
                  <select value={cap.font} onChange={(e) => set({ font: e.target.value })}
                    className="mt-1 w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-slate-200">
                    {CAPTION_FONTS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                  </select>
                </label>
                <label className="block">{tr('Position')}
                  <select value={cap.position} onChange={(e) => set({ position: e.target.value })}
                    className="mt-1 w-full rounded-lg bg-slate-800 border border-slate-700 px-2 py-1.5 text-slate-200">
                    <option value="auto">{tr('Automatic (over the original subtitle)')}</option>
                    <option value="bottom">{tr('Bottom')}</option>
                    <option value="middle">{tr('Middle')}</option>
                    <option value="top">{tr('Top')}</option>
                    <option value="custom">{tr('Custom (drag the subtitle)')}</option>
                  </select>
                </label>
                {cap.position === 'custom' && (
                  <label className="block sm:col-span-2">{tr('Height on the screen')}: <span className="text-slate-200">{Math.round((1 - cap.y) * 100)}%</span>
                    <input type="range" min={0.05} max={0.95} step={0.01} value={1 - cap.y} onChange={(e) => set({ y: Math.round((1 - Number(e.target.value)) * 100) / 100 })} className="w-full accent-purple-500" />
                  </label>
                )}
                <label className="block">{tr('Size')}: <span className="text-slate-200">{Math.round(cap.size * 100)}%</span>
                  <input type="range" min={0.6} max={1.8} step={0.05} value={cap.size} onChange={(e) => set({ size: Number(e.target.value) })} className="w-full accent-purple-500" />
                </label>
                <label className="block">{tr('Box opacity')}: <span className="text-slate-200">{Math.round(cap.bg_opacity * 100)}%</span>
                  <input type="range" min={0} max={1} step={0.05} value={cap.bg_opacity} onChange={(e) => set({ bg_opacity: Number(e.target.value) })} className="w-full accent-purple-500" />
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-400">
                <label className="flex items-center gap-1.5">{tr('Text')}
                  <input type="color" value={cap.color} onChange={(e) => set({ color: e.target.value.toUpperCase() })} className="w-8 h-7 rounded bg-transparent cursor-pointer" />
                </label>
                <label className="flex items-center gap-1.5">{tr('Box')}
                  <input type="color" value={cap.bg} onChange={(e) => set({ bg: e.target.value.toUpperCase() })} className="w-8 h-7 rounded bg-transparent cursor-pointer" />
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input type="checkbox" checked={!!cap.outline} onChange={(e) => set({ outline: e.target.checked ? '#000000' : '' })} className="w-4 h-4 accent-purple-500" />
                  {tr('Outline')}
                </label>
                {cap.outline && <input type="color" value={cap.outline} onChange={(e) => set({ outline: e.target.value.toUpperCase() })} className="w-8 h-7 rounded bg-transparent cursor-pointer" aria-label={tr('Outline')} />}
                <button type="button" onClick={() => onChange({ ...DEFAULT_CAPTION_STYLE })} className="ml-auto underline hover:text-slate-200">{tr('Reset style')}</button>
              </div>
            </div>
  );
}
