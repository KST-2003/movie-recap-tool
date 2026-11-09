import React from 'react';
import { RefreshCw, AlertTriangle as TriangleAlert } from 'lucide-react';
import { useI18n } from '../i18n.jsx';
import { Card, Stat, DayBars, useApi, ErrorBox, Loading } from './ui.jsx';

export default function Overview({ go }) {
  const { tr } = useI18n();
  const { data, error, loading, reload } = useApi('/api/admin/overview', { every: 10000 });
  if (!data) return error ? <ErrorBox error={error} onRetry={reload} /> : <Loading />;
  const { jobs_today: j, queue, users } = data;
  const cap = data.global_daily_minutes;
  const capPct = cap ? Math.min(100, (data.minutes_today / cap) * 100) : 0;
  return (
    <div className="space-y-4">
      <ErrorBox error={error} onRetry={reload} />
      {data.maintenance && (
        <button onClick={() => go('settings')} className="flex w-full items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-left text-sm text-amber-300">
          <TriangleAlert size={16} className="flex-shrink-0" /> {tr('Maintenance mode is ON: new videos are refused. Tap to change.')}
        </button>
      )}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={tr('Videos today')} value={j.total} sub={tr('{done} done · {failed} failed', { done: j.done, failed: j.error })} />
        <Stat label={tr('Minutes today')} value={data.minutes_today} sub={cap ? tr('of {n} daily ceiling', { n: cap }) : tr('no daily ceiling')} />
        <Stat label={tr('In progress')} value={queue.running + queue.queued} tone={queue.queued ? 'text-amber-300' : ''}
          sub={tr('{running} running · {waiting} waiting ({mode})', { running: queue.running, waiting: queue.queued, mode: queue.mode })} />
        <Stat label={tr('Users')} value={users.total} sub={tr('{today} active today · {enabled} enabled', { today: users.active_today, enabled: users.active })} />
      </div>
      {cap > 0 && (
        <Card title={tr('Global daily ceiling')}>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-800"><div className={`h-full ${capPct > 90 ? 'bg-red-500' : 'bg-purple-500'}`} style={{ width: `${capPct}%` }} /></div>
          <p className="mt-1.5 text-xs text-slate-400">{tr('{used} / {cap} min used today ({pct}%)', { used: data.minutes_today, cap, pct: Math.round(capPct) })}</p>
        </Card>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={tr('Videos per day (red = failed)')} action={<button onClick={reload} aria-label={tr('Refresh')} className="text-slate-400 hover:text-white"><RefreshCw size={15} className={loading ? 'animate-spin' : ''} /></button>}>
          <DayBars series={data.series} valueKey="jobs" errorKey="errors" unit={tr('videos')} />
        </Card>
        <Card title={tr('Video minutes per day')}>
          <DayBars series={data.series} valueKey="minutes" unit={tr('min')} color="#38bdf8" />
        </Card>
      </div>
    </div>
  );
}
