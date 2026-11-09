import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';

// The user's own usage: allowance meters, 30 days of minutes (one series, so no legend: the title names it),
// minutes by video type, and recent videos. A table view of the chart data is one click away.
const fmt = (n) => (Math.round(n * 10) / 10).toLocaleString('en-US', { maximumFractionDigits: 1 });
const shortDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const KINDS = [['recap', 'Recap voice-over'], ['full', 'Full movie voice-over'], ['subtitles', 'Subtitles only']];

function Allowance({ title, used, limit, note }) {
  const { tr } = useI18n();
  const left = Math.max(0, limit - used);
  const pct = limit > 0 ? Math.min(100, (used / limit) * 100) : 100;
  const state = used >= limit ? 'full' : pct >= 80 ? 'warn' : 'ok';
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <p className="text-xs text-slate-400">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{fmt(used)} <span className="text-sm font-normal text-slate-400">/ {limit} {tr('min')}</span></p>
      <div className="mt-3 h-2 rounded-full bg-slate-800 overflow-hidden">
        <div className={`h-full rounded-full ${state === 'full' ? 'bg-red-500' : state === 'warn' ? 'bg-amber-400' : 'bg-purple-400'}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        {state === 'full' ? `⛔ ${tr('Limit reached')} · ` : state === 'warn' ? `⚠ ${tr('Almost used up')} · ` : ''}
        {tr('{n} min left', { n: fmt(left) })} · {note}
      </p>
    </div>
  );
}

function DayChart({ days, limit }) {
  const { tr } = useI18n();
  const [hover, setHover] = useState(null);
  const [table, setTable] = useState(false);
  const max = Math.max(10, ...days.map((d) => d.minutes)) * 1.1;
  const total = days.reduce((a, d) => a + d.minutes, 0);
  const active = hover != null ? days[hover] : null;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">{tr('Minutes used per day (last 30 days)')}</h3>
          <p className="text-xs text-slate-400 mt-0.5">{tr('Total {n} min · daily limit {limit} min', { n: fmt(total), limit })}</p>
        </div>
        <button type="button" onClick={() => setTable(!table)} className="text-xs px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 shrink-0">
          {table ? tr('Show chart') : tr('Show table')}
        </button>
      </div>

      {!table ? (
        <>
          <div className="relative mt-4 h-40 flex items-end gap-[3px] border-b border-slate-700" onMouseLeave={() => setHover(null)}>
            {active && (
              <div className="absolute -top-1 right-0 z-10 rounded-lg bg-slate-800 border border-slate-700 px-2.5 py-1 text-xs text-slate-100 shadow">
                {shortDate(active.date)} · <b>{fmt(active.minutes)}</b> {tr('min')}
              </div>
            )}
            {days.map((d, i) => (
              <div
                key={d.date} className="flex-1 h-full flex items-end cursor-pointer"
                onMouseEnter={() => setHover(i)} onClick={() => setHover(i)}
                role="img" aria-label={`${shortDate(d.date)}: ${fmt(d.minutes)} ${tr('min')}`}
              >
                <div
                  className={`w-full rounded-t ${hover === i ? 'bg-purple-300' : 'bg-purple-400'}`}
                  style={{ height: d.minutes > 0 ? `max(3px, ${(d.minutes / max) * 100}%)` : '0' }}
                />
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-slate-500">
            <span>{shortDate(days[0].date)}</span><span>{shortDate(days[14].date)}</span><span>{shortDate(days[days.length - 1].date)}</span>
          </div>
        </>
      ) : (
        <div className="mt-3 max-h-56 overflow-y-auto rounded-lg border border-slate-800">
          <table className="w-full text-xs">
            <thead className="text-slate-400 bg-slate-800/50 sticky top-0"><tr><th className="text-left px-3 py-1.5">{tr('Date')}</th><th className="text-right px-3 py-1.5">{tr('Minutes')}</th></tr></thead>
            <tbody>
              {[...days].reverse().map((d) => (
                <tr key={d.date} className="border-t border-slate-800"><td className="px-3 py-1.5 text-slate-300">{shortDate(d.date)}</td><td className="px-3 py-1.5 text-right text-slate-100">{fmt(d.minutes)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function UsageDashboard({ apiBase, refreshKey }) {
  const { tr } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    setError('');
    axios.get(`${apiBase}/api/usage`).then((r) => live && setData(r.data)).catch((e) => live && setError(e.response?.data?.detail || e.message));
    return () => { live = false; };
  }, [apiBase, refreshKey]);

  if (error) return <div className="max-w-4xl mx-auto p-4 rounded-xl bg-red-950/50 border border-red-800 text-red-300 text-sm">{error}</div>;
  if (!data) return <div className="max-w-4xl mx-auto text-sm text-slate-400 p-4">{tr('Loading…')}</div>;

  const dayReset = new Date(data.resets.day).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const monthReset = new Date(data.resets.month).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  const kindTotal = KINDS.reduce((a, [k]) => a + (data.minutes_by_kind[k] || 0), 0) || 1;
  const monthUsed = data.month_used_seconds / 60;
  const dayOfMonth = new Date().getUTCDate();

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <h2 className="text-xl font-bold text-white">{tr('My usage')}</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Allowance title={tr('Today')} used={data.used_seconds / 60} limit={data.daily_minutes} note={tr('resets at {time}', { time: dayReset })} />
        <Allowance title={tr('This month')} used={monthUsed} limit={data.monthly_minutes} note={tr('resets on {date}', { date: monthReset })} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          [tr('Videos this month'), data.month_videos],
          [tr('Videos made in total'), data.total_videos],
          [tr('Average per video'), `${fmt(data.month_videos ? monthUsed / data.month_videos : 0)} ${tr('min')}`],
          [tr('Average per day'), `${fmt(monthUsed / dayOfMonth)} ${tr('min')}`],
        ].map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-800 bg-slate-900 p-3">
            <p className="text-xs text-slate-400">{label}</p>
            <p className="text-lg font-semibold text-white mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      <DayChart days={data.days} limit={data.daily_minutes} />

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">{tr('This month by video type')}</h3>
        <div className="space-y-3">
          {KINDS.map(([k, label]) => {
            const v = data.minutes_by_kind[k] || 0;
            return (
              <div key={k}>
                <div className="flex justify-between text-xs text-slate-300 mb-1"><span>{tr(label)}</span><span>{fmt(v)} {tr('min')}</span></div>
                <div className="h-2 rounded-full bg-slate-800 overflow-hidden"><div className="h-full rounded-full bg-purple-400" style={{ width: `${(v / kindTotal) * 100}%` }} /></div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="text-sm font-semibold text-slate-200 mb-1">{tr('Recent videos')}</h3>
        <p className="text-xs text-slate-500 mb-3">{tr('Editing and re-rendering a finished video does not use your minutes.')}</p>
        {data.recent.length === 0 ? (
          <p className="text-sm text-slate-400">{tr('No videos yet.')}</p>
        ) : (
          <ul className="divide-y divide-slate-800">
            {data.recent.map((j) => (
              <li key={j.id} className="py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                <span className="text-slate-300 w-36">{new Date(j.created_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                <span className="text-slate-200">{j.kind === 'edit' ? tr('Edit / re-render') : tr(KINDS.find(([k]) => k === j.kind)?.[1] || j.kind)}</span>
                <span className="text-slate-500">{j.aspect === 'original' ? tr('Original') : j.aspect}</span>
                <span className="ml-auto text-slate-200">{j.kind === 'edit' ? tr('free') : `${fmt(j.minutes)} ${tr('min')}`}</span>
                <span className={`px-2 py-0.5 rounded-full ${j.status === 'done' ? 'bg-emerald-900/50 text-emerald-300' : j.status === 'error' ? 'bg-red-900/50 text-red-300' : 'bg-slate-800 text-slate-300'}`}>
                  {j.status === 'done' ? '✓ ' : j.status === 'error' ? '✕ ' : ''}{tr(j.status)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
