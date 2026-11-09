import React, { useState } from 'react';
import axios from 'axios';
import { StopCircle as CircleStop } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Badge, Card, btnGhost, Pager, useApi, ErrorBox } from './ui.jsx';

const STATUS_FILTERS = ['', 'queued', 'running', 'done', 'error', 'cancelled'];

export default function JobsPage({ userFilter, clearUser }) {
  const { tr, trs } = useI18n();
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [actionError, setActionError] = useState('');
  const url = `/api/admin/jobs?page=${page}${status ? `&status=${status}` : ''}${userFilter ? `&user_id=${userFilter.id}` : ''}`;
  const { data, error, loading, reload } = useApi(url, { every: 8000 });
  const items = data?.items || [];

  const fmtDur = (s) => (s == null ? '–' : s >= 60 ? tr('{m}m {s}s', { m: Math.floor(s / 60), s: Math.round(s % 60) }) : tr('{s}s', { s: Math.round(s) }));
  const cancel = async (id) => {
    setActionError('');
    try { await axios.post(`/api/admin/jobs/${id}/cancel`); reload(); } catch (e) { setActionError(errText(e)); }
  };
  const mode = (j) => [j.mode ? tr(j.mode) : null, j.output === 'subtitles' ? tr('subs only') : null].filter(Boolean).join(' · ');
  const Stage = ({ j }) => (j.status === 'error' && j.error
    ? <span className="text-red-300" title={j.error}>{trs(j.error)}</span>
    : <span className="text-slate-400">{j.status === 'running' ? `${j.progress}% · ${trs(j.stage)}` : trs(j.stage)}</span>);
  const CancelBtn = ({ j }) => ['queued', 'running'].includes(j.status)
    ? <button className={`${btnGhost} !px-2.5 !py-1.5 text-red-300`} onClick={() => cancel(j.id)}><CircleStop size={14} />{tr('Cancel')}</button> : null;

  return (
    <div>
      {userFilter && (
        <div className="mb-3 flex items-center justify-between gap-2 rounded-xl bg-purple-500/10 px-3 py-2 text-sm text-purple-200">
          <span className="truncate">{tr('Videos of {email}', { email: userFilter.email })}</span><button className="flex-shrink-0 underline" onClick={clearUser}>{tr('Show all')}</button>
        </div>
      )}
      <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0">
        {STATUS_FILTERS.map((s) => (
          <button key={s || 'all'} onClick={() => { setStatus(s); setPage(1); }}
            className={`flex-shrink-0 rounded-full px-3 py-1.5 text-xs ${status === s ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>{tr(s || 'all')}</button>
        ))}
      </div>
      <ErrorBox error={error || actionError} onRetry={reload} />
      <Card className="overflow-hidden !p-0">
        <table className="hidden w-full table-fixed text-sm md:table">
          <thead className="bg-slate-900 text-left text-xs text-slate-400">
            <tr><th className="w-28 px-4 py-3">{tr('Status')}</th><th className="w-1/4 px-4 py-3">{tr('User')}</th><th className="px-4 py-3">{tr('Stage / error')}</th><th className="w-24 px-4 py-3">{tr('Length')}</th><th className="w-24 px-4 py-3">{tr('Took')}</th><th className="w-36 px-4 py-3">{tr('Started')}</th><th className="w-28 px-4 py-3" /></tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {items.map((j) => (
              <tr key={j.id} className="hover:bg-slate-800/40">
                <td className="px-4 py-3"><Badge status={j.status} /></td>
                <td className="px-4 py-3"><div className="truncate" title={j.email}>{j.email}</div><div className="text-[11px] text-slate-500">{mode(j)}</div></td>
                <td className="px-4 py-3"><div className="line-clamp-2 break-words text-xs"><Stage j={j} /></div></td>
                <td className="px-4 py-3 text-slate-300">{j.video_minutes ? tr('{n} min', { n: j.video_minutes }) : '–'}{j.cost_thb != null && <span className="block text-xs text-slate-500">{j.cost_thb} THB{j.cost_complete ? '' : ' *'}</span>}</td>
                <td className="px-4 py-3 text-slate-300">{fmtDur(j.run_seconds)}</td>
                <td className="px-4 py-3 text-slate-400">{fmtTime(j.created_at)}</td>
                <td className="px-4 py-3 text-right"><CancelBtn j={j} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="divide-y divide-slate-800 md:hidden">
          {items.map((j) => (
            <li key={j.id} className="p-4">
              <div className="flex items-center justify-between gap-2"><Badge status={j.status} /><span className="text-xs text-slate-500">{fmtTime(j.created_at)}</span></div>
              <div className="mt-1.5 break-all text-sm">{j.email}</div>
              <div className="mt-0.5 break-words text-xs"><Stage j={j} /></div>
              <div className="mt-2 flex items-center justify-between gap-2 text-xs text-slate-400">
                <span className="min-w-0">{[j.video_minutes ? tr('{n} min video', { n: j.video_minutes }) : '', j.run_seconds ? tr('took {t}', { t: fmtDur(j.run_seconds) }) : '', j.cost_thb != null ? `${j.cost_thb} THB${j.cost_complete ? '' : ' *'}` : '', mode(j)].filter(Boolean).join(' · ')}</span>
                <CancelBtn j={j} />
              </div>
            </li>
          ))}
        </ul>
        {!items.length && <p className="p-6 text-center text-sm text-slate-500">{loading ? tr('Loading…') : tr('No videos.')}</p>}
      </Card>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
    </div>
  );
}
