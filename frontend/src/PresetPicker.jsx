import React, { useEffect, useRef, useState } from 'react';
import { useI18n } from './i18n.jsx';

// "Preset" button at the top of the Create form: pick one of your presets (or a Recat preset) and the form is filled in with it.
export default function PresetPicker({ presets, active, onPick, onManage, onClear }) {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false); };
    const key = (e) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', key);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', key); };
  }, [open]);
  const mine = presets?.mine || [];
  const shared = presets?.shared || [];
  const item = (p, badge) => (
    <li key={`${badge ? 's' : 'm'}${p.id}`}>
      <button type="button" onClick={() => { onPick(p); setOpen(false); }}
        className={`flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm hover:bg-violet-50 ${active === p.id + (badge ? 's' : 'm') ? 'bg-violet-50 font-semibold text-violet-600' : 'text-ink'}`}>
        <span className="min-w-0 flex-1 truncate">{p.name}</span>
        {badge && <span className="shrink-0 rounded-full bg-violet-500 px-2 py-0.5 text-[10px] font-semibold text-white">Recat</span>}
      </button>
    </li>
  );
  return (
    <div ref={box} className="relative flex items-center gap-2">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex items-center gap-2 rounded-2xl border border-violet-200 bg-white px-3.5 py-2 text-sm font-semibold text-violet-600 shadow-card hover:bg-violet-50">
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" /></svg>
        {active ? tr('Preset: {name}', { name: [...mine.map((p) => [p.id + 'm', p.name]), ...shared.map((p) => [p.id + 's', p.name])].find(([k]) => k === active)?.[1] || '' }) : tr('Preset')}
      </button>
      {active && <button type="button" onClick={onClear} className="text-xs text-ink-faint underline">{tr('Clear')}</button>}
      {open && (
        <div className="absolute left-0 top-full z-40 mt-2 w-72 max-w-[85vw] rounded-2xl border border-violet-100 bg-white p-2 shadow-xl">
          {mine.length === 0 && shared.length === 0 && <p className="px-3 py-2 text-xs text-ink-soft">{tr('You have no presets yet.')}</p>}
          {mine.length > 0 && <p className="px-3 pt-1 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{tr('My presets')}</p>}
          <ul>{mine.map((p) => item(p, false))}</ul>
          {shared.length > 0 && <p className="px-3 pt-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">{tr('Recat presets')}</p>}
          <ul>{shared.map((p) => item(p, true))}</ul>
          <button type="button" onClick={() => { setOpen(false); onManage(); }} className="mt-1 w-full rounded-xl border-t border-violet-100 px-3 py-2 text-left text-sm text-violet-600 hover:bg-violet-50">
            {tr('Make or edit presets…')}
          </button>
        </div>
      )}
    </div>
  );
}
