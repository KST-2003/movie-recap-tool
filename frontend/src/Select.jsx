import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

/**
 * Our own dropdown (no system picker). options: [{ value, label, group? }] (an option with the same `group` text is listed under a heading).
 * size: 'md' (form fields) | 'sm' (compact, inside the editor). The menu is drawn with position: fixed so no parent can clip it.
 */
export default function Select({ value, onChange, options, size = 'md', className = '', placeholder = '', disabled = false, title }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pos, setPos] = useState(null);
  const btn = useRef(null);
  const menu = useRef(null);
  const selected = options.find((o) => o.value === value);
  const small = size === 'sm';

  const flat = useMemo(() => {   // options in display order with group headings between them
    const rows = [];
    let last;
    options.forEach((o, i) => {
      if (o.group && o.group !== last) rows.push({ heading: o.group });
      last = o.group;
      rows.push({ ...o, index: i });
    });
    return rows;
  }, [options]);

  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return;
    const below = window.innerHeight - r.bottom, above = r.top;
    const up = below < 220 && above > below;
    setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 200) - 8)), width: Math.max(r.width, 200),
      ...(up ? { bottom: window.innerHeight - r.top + 6, maxH: Math.min(320, above - 12) } : { top: r.bottom + 6, maxH: Math.min(320, below - 12) }) });
  };
  useLayoutEffect(() => { if (open) place(); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!btn.current?.contains(e.target) && !menu.current?.contains(e.target)) setOpen(false); };
    const away = (e) => { if (!menu.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    window.addEventListener('resize', place); window.addEventListener('scroll', away, true);
    return () => { document.removeEventListener('pointerdown', close); window.removeEventListener('resize', place); window.removeEventListener('scroll', away, true); };
  }, [open]);
  useEffect(() => {   // keep the highlighted row in view
    if (open && active >= 0) menu.current?.querySelector(`[data-i="${active}"]`)?.scrollIntoView({ block: 'nearest' });
  }, [active, open]);

  const openMenu = () => { if (disabled) return; setActive(Math.max(0, options.findIndex((o) => o.value === value))); setOpen(true); };
  const pick = (o) => { setOpen(false); btn.current?.focus(); if (o.value !== value) onChange(o.value); };
  const onKey = (e) => {
    if (disabled) return;
    if (!open) { if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) { e.preventDefault(); openMenu(); } return; }
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(options.length - 1, a + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
    else if (e.key === 'Home') { e.preventDefault(); setActive(0); }
    else if (e.key === 'End') { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (options[active]) pick(options[active]); }
    else if (e.key === 'Tab') setOpen(false);
  };

  return (
    <>
      <button
        ref={btn} type="button" disabled={disabled} title={title} aria-haspopup="listbox" aria-expanded={open}
        onClick={() => (open ? setOpen(false) : openMenu())} onKeyDown={onKey}
        className={`group flex items-center justify-between gap-2 text-left border transition-all duration-200 ease-out outline-none
          focus-visible:ring-2 focus-visible:ring-purple-400/70 disabled:opacity-50 disabled:cursor-not-allowed
          ${small ? 'rounded-lg px-2 py-1 text-xs' : 'rounded-xl px-3 py-2.5 text-sm'}
          ${open ? 'border-purple-400 bg-slate-800 shadow-[0_0_0_3px_rgba(168,85,247,0.18)]' : 'border-slate-700 bg-slate-800/80 hover:border-slate-500'}
          ${className || 'w-full'}`}
      >
        <span className={`min-w-0 truncate ${selected ? 'text-slate-100' : 'text-slate-400'}`}>{selected ? selected.label : placeholder}</span>
        <svg viewBox="0 0 20 20" className={`shrink-0 ${small ? 'h-3.5 w-3.5' : 'h-4 w-4'} text-slate-400 transition-transform duration-200 ${open ? 'rotate-180 text-purple-300' : ''}`} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 8l5 5 5-5" />
        </svg>
      </button>
      {open && pos && (
        <div
          ref={menu} role="listbox"
          style={{ position: 'fixed', left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxH, zIndex: 1000 }}
          className="overflow-y-auto overscroll-contain rounded-xl border border-slate-600 bg-slate-900/95 backdrop-blur p-1 shadow-2xl shadow-black/60 animate-[selectIn_140ms_ease-out]"
        >
          {flat.map((row, n) => (row.heading
            ? <div key={`h${n}`} className="px-2.5 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">{row.heading}</div>
            : (
              <div
                key={row.index} data-i={row.index} role="option" aria-selected={row.value === value}
                onPointerEnter={() => setActive(row.index)} onClick={() => pick(row)}
                className={`flex items-center gap-2 cursor-pointer rounded-lg px-2.5 ${small ? 'py-1.5 text-xs' : 'py-2 text-sm'} transition-colors duration-100
                  ${row.index === active ? 'bg-purple-600/30 text-white' : 'text-slate-200'} ${row.value === value ? 'font-semibold' : ''}`}
              >
                <span className="min-w-0 flex-1">{row.label}</span>
                {row.value === value && (
                  <svg viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-purple-300" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 10.5l4 4 8-9" /></svg>
                )}
              </div>
            )))}
        </div>
      )}
    </>
  );
}
