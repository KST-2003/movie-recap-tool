import React from 'react';
import { useI18n } from '../i18n.jsx';
import { STATUS_STYLE, Card, Stat, useApi, ErrorBox, Loading } from './ui.jsx';

export default function TtsPage() {
  const { tr } = useI18n();
  const { data, error, reload } = useApi('/api/admin/tts', { every: 15000 });
  if (!data) return error ? <ErrorBox error={error} onRetry={reload} /> : <Loading />;
  const total = data.models.reduce((a, m) => a + m.per_day, 0);
  const left = data.models.reduce((a, m) => a + m.remaining, 0);
  const fmtLeft = (s) => tr('{h}h {m}m', { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60) });
  return (
    <div className="space-y-4">
      <ErrorBox error={error} onRetry={reload} />
      {data.all_blocked && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{tr('Every voice model is out of requests: new videos with a voice-over are refused until a limit resets.')}</div>}
      <div className="grid grid-cols-2 gap-3">
        <Stat label={tr('Requests left today')} value={left} sub={tr('of {n} (all models)', { n: total })} />
        <Stat label={tr('Quota day (Pacific)')} value={data.day.slice(5)} sub={tr('resets at midnight PT')} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {data.models.map((m) => {
          const pct = m.per_day ? Math.min(100, (m.used_today / m.per_day) * 100) : 100;
          const blocked = m.blocked_seconds > 0;
          const state = blocked ? ['blocked', 'error'] : m.remaining === 0 ? ['exhausted', 'cancelled'] : ['available', 'done'];
          return (
            <Card key={m.model}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 break-all text-sm font-medium">{m.model}</div>
                <span className={`inline-block flex-shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[state[1]]}`}>{tr(state[0])}</span>
              </div>
              {blocked && <div className="mt-0.5 text-[11px] text-slate-500">{tr('Google refused it, resets in {t}', { t: fmtLeft(m.blocked_seconds) })}</div>}
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800"><div className={`h-full ${pct > 90 ? 'bg-red-500' : 'bg-purple-500'}`} style={{ width: `${pct}%` }} /></div>
              <div className="mt-1.5 flex justify-between text-xs text-slate-400"><span>{tr('{used} / {limit} today', { used: m.used_today, limit: m.per_day })}</span><span>{tr('{n}/min', { n: m.per_minute })}</span></div>
            </Card>
          );
        })}
      </div>
      <p className="text-xs text-slate-500">{tr("Counts come from this server's own tally (data/tts_usage.json) plus Google's refusals; Google's dashboard is the source of truth.")}</p>
    </div>
  );
}
