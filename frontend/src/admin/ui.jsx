import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { X, AlertTriangle as TriangleAlert } from 'lucide-react';
import { useI18n } from '../i18n.jsx';

// Shared pieces of the admin pages: small components, button/field styles and the data hook.

export const errText = (e) => e?.response?.data?.detail || e?.message || 'Request failed';
export const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '–');


export const STATUS_STYLE = {
  done: 'bg-emerald-500/15 text-emerald-300', running: 'bg-sky-500/15 text-sky-300', queued: 'bg-amber-500/15 text-amber-300',
  error: 'bg-red-500/15 text-red-300', cancelled: 'bg-slate-500/20 text-slate-300',
};
export function Badge({ status }) {
  const { tr } = useI18n();
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[status] || 'bg-slate-700 text-slate-300'}`}>{tr(status)}</span>;
}

export const Card = ({ title, action, children, className = '' }) => (
  <section className={`rounded-2xl border border-slate-800 bg-slate-900 p-4 ${className}`}>
    {(title || action) && (
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">{title}</h2>{action}
      </div>
    )}
    {children}
  </section>
);

export const Stat = ({ label, value, sub, tone = '' }) => (
  <div className="min-w-0 rounded-2xl border border-slate-800 bg-slate-900 p-4">
    <div className="truncate text-xs text-slate-400">{label}</div>
    <div className={`mt-1 truncate text-2xl font-bold ${tone}`}>{value}</div>
    {sub && <div className="mt-0.5 truncate text-xs text-slate-500">{sub}</div>}
  </div>
);

export const btn = 'inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition disabled:opacity-50';
export const btnPrimary = `${btn} bg-purple-600 hover:bg-purple-500 text-white`;
export const btnGhost = `${btn} border border-slate-700 text-slate-200 hover:bg-slate-800`;
export const field = 'w-full rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-purple-500';

export function Toggle({ checked, onChange, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={checked} disabled={disabled} onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 flex-shrink-0 rounded-full transition disabled:opacity-50 ${checked ? 'bg-purple-600' : 'bg-slate-700'}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${checked ? 'left-[22px]' : 'left-0.5'}`} />
    </button>
  );
}

export function Pager({ page, perPage, total, onPage }) {
  const { tr } = useI18n();
  const pages = Math.max(1, Math.ceil(total / perPage));
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
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
export function Sheet({ title, onClose, children }) {
  const { tr } = useI18n();
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 md:items-center" onClick={onClose}>
      <div className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl border border-slate-800 bg-slate-900 p-5 md:max-w-md md:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between gap-2">
          <h3 className="min-w-0 break-all font-semibold">{title}</h3>
          <button onClick={onClose} aria-label={tr('Close')} className="flex-shrink-0 rounded-lg p-1 text-slate-400 hover:bg-slate-800"><X size={18} /></button>
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
                {eh > 0 && <div className="w-full rounded-t bg-red-500" style={{ height: `${(eh / h) * 100}%` }} />}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
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
    <div className="mb-3 flex items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
      <span className="flex min-w-0 items-center gap-2"><TriangleAlert size={16} className="flex-shrink-0" /><span className="break-words">{trs(error)}</span></span>
      {onRetry && <button onClick={onRetry} className="flex-shrink-0 underline">{tr('Retry')}</button>}
    </div>
  );
}

export const Loading = () => { const { tr } = useI18n(); return <p className="text-slate-400">{tr('Loading…')}</p>; };
