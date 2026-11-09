import React, { useState } from 'react';
import { useI18n } from './i18n.jsx';
import { fmtTime, Card, Pager, useApi, ErrorBox } from './ui.jsx';

// One readable line per change recorded in an audit entry
function describe(tr, e) {
  const d = e.details || {};
  const lines = [];
  if (e.action === 'user.create') {
    lines.push(tr('Created user {email}', { email: e.target_label }));
    lines.push(tr('{n} min/day', { n: d.daily_minutes }) + (d.is_admin ? ` · ${tr('admin')}` : ''));
  } else if (e.action === 'job.cancel') {
    lines.push(tr('Cancelled video {id} of {email}', { id: e.target_id, email: e.target_label || '?' }));
  } else if (e.action === 'user.update' || e.action === 'settings.update') {
    if (e.action === 'user.update') lines.push(tr('Changed user {email}', { email: e.target_label }));
    for (const [k, v] of Object.entries(d)) {
      if (k === 'daily_minutes') lines.push(tr('Daily minutes: {from} → {to}', { from: v.from, to: v.to }));
      else if (k === 'monthly_minutes') lines.push(tr('Monthly minutes: {from} → {to}', { from: v.from, to: v.to }));
      else if (k === 'is_active') lines.push(v.to ? tr('Account enabled') : tr('Account disabled'));
      else if (k === 'is_admin') lines.push(v.to ? tr('Made admin') : tr('Removed admin'));
      else if (k === 'password_reset') lines.push(tr('Password reset'));
      else if (k === 'maintenance') lines.push(v.to ? tr('Maintenance mode turned on') : tr('Maintenance mode turned off'));
      else if (k === 'global_daily_minutes') lines.push(tr('Global daily ceiling: {from} → {to} min', { from: v.from, to: v.to }));
      else lines.push(`${k}: ${JSON.stringify(v)}`);
    }
  }
  return lines;
}

const ACTION_STYLE = { 'user.create': 'bg-emerald-500/15 text-emerald-300', 'user.update': 'bg-sky-500/15 text-sky-300', 'job.cancel': 'bg-amber-500/15 text-amber-300', 'settings.update': 'bg-purple-500/15 text-purple-300' };

export default function AuditPage() {
  const { tr } = useI18n();
  const [action, setAction] = useState('');
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApi(`/api/admin/audit?page=${page}${action ? `&action=${action}` : ''}`, { every: 15000 });
  const items = data?.items || [];
  const Tag = ({ a }) => <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-medium ${ACTION_STYLE[a] || 'bg-slate-700 text-slate-300'}`}>{tr(a)}</span>;
  const Lines = ({ e }) => <ul className="space-y-0.5">{describe(tr, e).map((l, i) => <li key={i} className="break-words">{l}</li>)}</ul>;

  return (
    <div>
      <p className="mb-3 text-sm text-slate-400">{tr('Every change made from this dashboard: who did it, what changed, and when. Passwords are never recorded.')}</p>
      <div className="-mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pb-1 md:mx-0 md:px-0">
        {['', ...(data?.actions || ['user.create', 'user.update', 'job.cancel', 'settings.update'])].map((a) => (
          <button key={a || 'all'} onClick={() => { setAction(a); setPage(1); }}
            className={`flex-shrink-0 rounded-full px-3 py-1.5 text-xs ${action === a ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}>{tr(a || 'all')}</button>
        ))}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <Card className="overflow-hidden !p-0">
        <table className="hidden w-full table-fixed text-sm md:table">
          <thead className="bg-slate-900 text-left text-xs text-slate-400">
            <tr><th className="w-36 px-4 py-3">{tr('When')}</th><th className="w-1/4 px-4 py-3">{tr('Admin')}</th><th className="w-36 px-4 py-3">{tr('Action')}</th><th className="px-4 py-3">{tr('What changed')}</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {items.map((e) => (
              <tr key={e.id} className="align-top hover:bg-slate-800/40">
                <td className="px-4 py-3 text-slate-400">{fmtTime(e.created_at)}</td>
                <td className="px-4 py-3"><div className="truncate" title={e.admin_email}>{e.admin_email}</div></td>
                <td className="px-4 py-3"><Tag a={e.action} /></td>
                <td className="px-4 py-3 text-xs text-slate-300"><Lines e={e} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="divide-y divide-slate-800 md:hidden">
          {items.map((e) => (
            <li key={e.id} className="p-4">
              <div className="flex items-center justify-between gap-2"><Tag a={e.action} /><span className="text-xs text-slate-500">{fmtTime(e.created_at)}</span></div>
              <div className="mt-1.5 text-sm text-slate-200"><Lines e={e} /></div>
              <div className="mt-1 break-all text-xs text-slate-500">{tr('by {email}', { email: e.admin_email })}</div>
            </li>
          ))}
        </ul>
        {!items.length && <p className="p-6 text-center text-sm text-slate-500">{loading ? tr('Loading…') : tr('Nothing recorded yet.')}</p>}
      </Card>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
    </div>
  );
}
