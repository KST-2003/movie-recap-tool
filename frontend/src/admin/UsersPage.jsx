import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Search, Plus, ShieldCheck, Ban, Pencil } from 'lucide-react';
import { useI18n } from '../i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, btnGhost, field, Toggle, Pager, Sheet, useApi, ErrorBox } from './ui.jsx';

function UserForm({ user, defaultMinutes, me, onClose, onSaved }) {
  const { tr, trs } = useI18n();
  const creating = !user;
  const [email, setEmail] = useState(user?.email || '');
  const [password, setPassword] = useState('');
  const [minutes, setMinutes] = useState(user?.daily_minutes ?? defaultMinutes ?? 20);
  const [active, setActive] = useState(user?.is_active ?? true);
  const [isAdmin, setIsAdmin] = useState(user?.is_admin ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const self = !creating && user.id === me;

  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setError('');
    try {
      if (creating) {
        await axios.post('/api/admin/users', { email, password, daily_minutes: Number(minutes), is_admin: isAdmin });
      } else {
        const body = { daily_minutes: Number(minutes), is_active: active, is_admin: isAdmin };
        if (password) body.password = password;
        await axios.patch(`/api/admin/users/${user.id}`, body);
      }
      onSaved();
    } catch (err) { setError(errText(err)); setBusy(false); }
  };

  return (
    <Sheet title={creating ? tr('Add user') : user.email} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        {creating && <input className={field} type="email" placeholder={tr('Email')} value={email} onChange={(e) => setEmail(e.target.value)} required />}
        <input className={field} type="text" autoComplete="new-password" placeholder={creating ? tr('Password (8+ characters)') : tr('New password (leave empty to keep)')}
          value={password} onChange={(e) => setPassword(e.target.value)} required={creating} minLength={password || creating ? 8 : undefined} />
        <label className="block text-xs text-slate-400">{tr('Daily minutes')}
          <input className={`${field} mt-1`} type="number" min="0" value={minutes} onChange={(e) => setMinutes(e.target.value)} required />
        </label>
        <div className="flex items-center justify-between rounded-xl bg-slate-800/60 px-3 py-2 text-sm">
          <span>{tr('Admin')}</span><Toggle checked={isAdmin} onChange={setIsAdmin} disabled={self} />
        </div>
        {!creating && (
          <div className="flex items-center justify-between rounded-xl bg-slate-800/60 px-3 py-2 text-sm">
            <span>{tr('Account enabled')}</span><Toggle checked={active} onChange={setActive} disabled={self} />
          </div>
        )}
        {self && <p className="text-xs text-slate-500">{tr('You cannot disable or demote your own account.')}</p>}
        {error && <p className="text-sm text-red-400">{trs(error)}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className={btnGhost} onClick={onClose}>{tr('Cancel')}</button>
          <button className={btnPrimary} disabled={busy}>{creating ? tr('Create') : tr('Save')}</button>
        </div>
      </form>
    </Sheet>
  );
}

export default function UsersPage({ me, openJobsFor }) {
  const { tr } = useI18n();
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(undefined); // undefined = closed, null = new user, object = edit
  const { data, error, loading, reload } = useApi(`/api/admin/users?q=${encodeURIComponent(query)}&page=${page}`, { every: 15000 });

  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const items = data?.items || [];
  const usage = (u) => tr('{used} / {limit} min', { used: u.used_minutes_today, limit: u.daily_minutes });
  const pct = (u) => Math.min(100, u.daily_minutes ? (u.used_minutes_today / u.daily_minutes) * 100 : 100);
  const Meter = ({ u }) => <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-slate-800"><div className={`h-full ${pct(u) > 90 ? 'bg-red-500' : 'bg-purple-500'}`} style={{ width: `${pct(u)}%` }} /></div>;
  const Tags = ({ u }) => (<>
    {u.is_admin && <span className="inline-flex items-center gap-1 rounded-full bg-purple-500/15 px-2 py-0.5 text-[11px] text-purple-300"><ShieldCheck size={11} />{tr('admin')}</span>}
    {!u.is_active && <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-[11px] text-red-300"><Ban size={11} />{tr('disabled')}</span>}
  </>);

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <div className="relative min-w-0 flex-1">
          <Search size={15} className="absolute left-3 top-2.5 text-slate-500" />
          <input className={`${field} pl-9`} placeholder={tr('Search email…')} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className={btnPrimary} onClick={() => setEditing(null)} aria-label={tr('Add user')}><Plus size={16} /><span className="hidden sm:inline">{tr('Add user')}</span></button>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <Card className="overflow-hidden !p-0">
        <table className="hidden w-full text-sm md:table">
          <thead className="bg-slate-900 text-left text-xs text-slate-400">
            <tr><th className="px-4 py-3">{tr('Email')}</th><th className="px-4 py-3">{tr('Today')}</th><th className="px-4 py-3">{tr('Joined')}</th><th className="px-4 py-3" /></tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {items.map((u) => (
              <tr key={u.id} className="hover:bg-slate-800/40">
                <td className="px-4 py-3"><div className="flex flex-wrap items-center gap-2"><span className="break-all">{u.email}</span><Tags u={u} /></div></td>
                <td className="px-4 py-3 text-slate-300"><div>{usage(u)}</div><Meter u={u} /></td>
                <td className="px-4 py-3 text-slate-400">{fmtTime(u.created_at)}</td>
                <td className="px-4 py-3"><div className="flex justify-end gap-2">
                  <button className={btnGhost} onClick={() => openJobsFor(u)}>{tr('Videos')}</button>
                  <button className={btnGhost} onClick={() => setEditing(u)}><Pencil size={14} />{tr('Edit')}</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="divide-y divide-slate-800 md:hidden">
          {items.map((u) => (
            <li key={u.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0"><div className="break-all text-sm font-medium">{u.email}</div><div className="mt-1 flex flex-wrap gap-1.5"><Tags u={u} /></div></div>
                <button className={btnGhost} onClick={() => setEditing(u)} aria-label={tr('Edit')}><Pencil size={14} /></button>
              </div>
              <div className="mt-2 flex items-end justify-between text-xs text-slate-400">
                <div>{tr('Today')} {usage(u)}<Meter u={u} /></div>
                <button className="underline" onClick={() => openJobsFor(u)}>{tr('Videos')}</button>
              </div>
            </li>
          ))}
        </ul>
        {!items.length && <p className="p-6 text-center text-sm text-slate-500">{loading ? tr('Loading…') : tr('No users found.')}</p>}
      </Card>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
      {editing !== undefined && (
        <UserForm user={editing} me={me} defaultMinutes={data?.default_daily_minutes} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); reload(); }} />
      )}
    </div>
  );
}
