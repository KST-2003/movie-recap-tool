import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { X, AlertTriangle as TriangleAlert } from 'lucide-react';
import { useI18n } from './i18n.jsx';

// Shared pieces of the admin pages: small components, button/field styles and the data hook.

export const errText = (e) => e?.response?.data?.detail || e?.message || 'Request failed';
export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '–');


export const STATUS_STYLE = {
  done: 'bg-emerald-500/15 text-emerald-700', running: 'bg-sky-500/15 text-sky-600', queued: 'bg-amber-500/15 text-amber-700',
  error: 'bg-red-500/15 text-rose-600', cancelled: 'bg-violet-300/20 text-ink-soft',
};
export function Badge({ status }) {
  const { tr } = useI18n();
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[status] || 'bg-violet-100 text-ink-soft'}`}>{tr(status)}</span>;
}

export const Card = ({ title, action, children, className = '' }) => (
  <section className={`rounded-2xl border border-violet-100 bg-white p-4 ${className}`}>
    {(title || action) && (
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>{action}
      </div>
    )}
    {children}
  </section>
);

export const Stat = ({ label, value, sub, tone = '' }) => (
  <div className="min-w-0 rounded-2xl border border-violet-100 bg-white p-4">
    <div className="truncate text-xs text-ink-soft">{label}</div>
    <div className={`mt-1 truncate text-2xl font-bold ${tone}`}>{value}</div>
    {sub && <div className="mt-0.5 truncate text-xs text-ink-faint">{sub}</div>}
  </div>
);

export const btn = 'inline-flex items-center justify-center gap-1.5 rounded-2xl px-3 py-2 text-sm font-medium transition disabled:opacity-50';
export const btnPrimary = `${btn} bg-violet-500 hover:bg-violet-600 text-white`;
export const btnGhost = `${btn} border border-violet-200 text-ink hover:bg-violet-50`;
export const field = 'w-full rounded-2xl bg-violet-50 border border-violet-200 px-3 py-2 text-sm text-ink outline-none focus:border-violet-400';

export function Toggle({ checked, onChange, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 flex-shrink-0 rounded-full transition disabled:opacity-50 ${checked ? 'bg-violet-500 text-white' : 'bg-violet-200'}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  );
}

export function Pager({ page, perPage, total, onPage }) {
  const { tr } = useI18n();
  const pages = Math.max(1, Math.ceil(total / perPage));
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
      <span>{tr('{n} total', { n: total })}</span>
      <div className="flex items-center gap-2">
        <button className={btnGhost} disabled={page <= 1} onClick={() => onPage(page - 1)}>{tr('Prev')}</button>
        <span>{page} / {pages}</span>
        <button className={btnGhost} disabled={page >= pages} onClick={() => onPage(page + 1)}>{tr('Next')}</button>
      </div>
    </div>
  );
}

// Bottom sheet on phones, centred dialog on larger screens
export function Sheet({ title, onClose, children, wide = false }) {
  const { tr } = useI18n();
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 backdrop-blur-sm md:items-center" onClick={onClose}>
      {/* dvh = the VISIBLE height on phones (vh counts the area behind the address bar, which pushed the top of the sheet off screen) */}
      <div className={`max-h-[85vh] w-full overflow-y-auto overscroll-contain rounded-t-2xl border border-violet-100 bg-white px-5 pb-8 ${wide ? 'md:max-w-3xl' : 'md:max-w-md'} md:rounded-2xl md:pb-5`} style={{ maxHeight: '85dvh' }} onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 z-10 -mx-5 mb-4 flex items-center justify-between gap-2 bg-white px-5 pb-3 pt-5">
          <h3 className="min-w-0 break-all font-semibold">{title}</h3>
          <button onClick={onClose} aria-label={tr('Close')} className="flex-shrink-0 rounded-lg p-1 text-ink-soft hover:bg-violet-50"><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

// One bar per day (red part = failed), no chart library
export function DayBars({ series, valueKey, unit, color = '#a855f7', errorKey }) {
  const { tr } = useI18n();
  const max = Math.max(1, ...series.map((d) => d[valueKey]));
  return (
    <div>
      <div className="flex h-36 items-end gap-1">
        {series.map((d) => {
          const h = (d[valueKey] / max) * 100;
          const eh = errorKey && d[valueKey] ? (d[errorKey] / d[valueKey]) * h : 0;
          const tip = `${d.day}: ${d[valueKey]} ${unit}${errorKey ? `, ${tr('{n} failed', { n: d[errorKey] })}` : ''}`;
          return (
            <div key={d.day} className="relative flex h-full min-w-0 flex-1 flex-col justify-end" title={tip}>
              <div className="w-full rounded-t" style={{ height: `${Math.max(h, d[valueKey] ? 2 : 0)}%`, background: color, opacity: 0.9 }}>
                {eh > 0 && <div className="w-full rounded-t bg-red-500 text-white" style={{ height: `${(eh / h) * 100}%` }} />}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-ink-faint">
        <span>{series[0]?.day.slice(5)}</span><span>{tr('max {n}', { n: `${Math.round(max * 10) / 10} ${unit}` })}</span><span>{series[series.length - 1]?.day.slice(5)}</span>
      </div>
    </div>
  );
}

// ---- data hook: load + optional auto refresh ----

export function useApi(path, { every = 0 } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const load = useCallback(async () => {
    try {
      const r = await axios.get(path);
      if (alive.current) { setData(r.data); setError(''); }
    } catch (e) {
      if (alive.current) setError(errText(e));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    setLoading(true);
    load();
    const id = every ? setInterval(load, every) : null;
    return () => { alive.current = false; if (id) clearInterval(id); };
  }, [load, every]);
  return { data, error, loading, reload: load };
}

export function ErrorBox({ error, onRetry }) {
  const { tr, trs } = useI18n();
  if (!error) return null;
  return (
    <div className="mb-3 flex items-center justify-between gap-3 rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-rose-600">
      <span className="flex min-w-0 items-center gap-2"><TriangleAlert size={16} className="flex-shrink-0" /><span className="break-words">{trs(error)}</span></span>
      {onRetry && <button onClick={onRetry} className="flex-shrink-0 underline">{tr('Retry')}</button>}
    </div>
  );
}

export const Loading = () => { const { tr } = useI18n(); return <p className="text-ink-soft">{tr('Loading…')}</p>; };
