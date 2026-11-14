import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Search, Plus, ShieldCheck, Pencil, Copy, KeyRound, Monitor, Trash2 } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, btnGhost, field, Toggle, Pager, Sheet, useApi, ErrorBox } from './ui.jsx';

const STATUS_STYLE = {
  active: 'bg-emerald-500/15 text-emerald-700', paused: 'bg-amber-500/15 text-amber-700',
  deactivated: 'bg-violet-300/20 text-ink-soft', banned: 'bg-red-500/15 text-rose-600',
};
const STATUS_HELP = {
  active: 'Can log in and use the app.',
  paused: 'Temporarily stopped. Signed out at once; turn it back on any time.',
  deactivated: 'Account closed (for example the plan ended). Signed out at once; can be turned back on.',
  banned: 'Blocked for breaking the rules. Signed out at once and the running videos are cancelled.',
};

function StatusChip({ status }) {
  const { tr } = useI18n();
  return <span className={`rounded-full px-2 py-0.5 text-[11px] ${STATUS_STYLE[status] || STATUS_STYLE.active}`}>{tr(status)}</span>;
}

// Shown ONCE after a login is made or a password is regenerated: the server keeps only a hash, so it cannot be shown again.
function Credentials({ username, password, onClose }) {
  const { tr } = useI18n();
  const [copied, setCopied] = useState(false);
  const text = `${tr('Username')}: ${username}\n${tr('Password')}: ${password}`;
  const copy = async () => { try { await navigator.clipboard.writeText(text); setCopied(true); } catch (e) { setCopied(false); } };
  return (
    <Sheet title={tr('Login details')} onClose={onClose}>
      <div className="space-y-3">
        <p className="rounded-2xl bg-amber-500/10 p-3 text-xs text-amber-700">{tr('Send these to the user now. The password is shown only this once: it is stored scrambled and cannot be read again. If it is lost, make a new one.')}</p>
        <dl className="space-y-2 rounded-2xl bg-violet-50/60 p-3 text-sm">
          <div className="flex justify-between gap-3"><dt className="text-ink-soft">{tr('Username')}</dt><dd className="break-all font-mono">{username}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-ink-soft">{tr('Password')}</dt><dd className="break-all font-mono">{password}</dd></div>
        </dl>
        <div className="flex justify-end gap-2">
          <button className={btnGhost} onClick={copy}><Copy size={14} />{copied ? tr('Copied') : tr('Copy')}</button>
          <button className={btnPrimary} onClick={onClose}>{tr('Done')}</button>
        </div>
      </div>
    </Sheet>
  );
}

const DevicePolicy = ({ value, onChange }) => {
  const { tr } = useI18n();
  return (
    <label className="block text-xs text-ink-soft">{tr('Devices that may use this login')}
      <select className={`${field} mt-1`} value={String(value)} onChange={(e) => onChange(Number(e.target.value))}>
        <option value="1">{tr('One device only')}</option>
        <option value="2">{tr('Up to 2 devices')}</option>
        <option value="3">{tr('Up to 3 devices')}</option>
        <option value="0">{tr('Any number of devices')}</option>
      </select>
    </label>
  );
};

function RolePicker({ value, onChange, disabled, note }) {
  const { tr } = useI18n();
  return (
    <div>
      <p className="mb-1.5 text-xs text-ink-soft">{tr('Role')}</p>
      <div className="grid grid-cols-2 gap-2">
        {['user', 'admin'].map((r) => (
          <button type="button" key={r} disabled={disabled} onClick={() => onChange(r)}
            className={`rounded-2xl border px-2 py-2 text-sm disabled:opacity-50 ${value === r ? 'border-violet-400 bg-violet-500/30 text-ink' : 'border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{tr(r === 'user' ? 'User' : 'Admin')}</button>
        ))}
      </div>
      <p className="mt-1.5 text-xs text-ink-faint">{note || tr('Admin: can use the dashboard (users, jobs, top-ups, voice models, audit log) but not Settings.')}</p>
    </div>
  );
}

function CreateForm({ defaultMinutes, defaultMonthly, superadmin, onClose, onCreated }) {
  const { tr, trs } = useI18n();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [minutes, setMinutes] = useState(defaultMinutes ?? 100);
  const [monthly, setMonthly] = useState(defaultMonthly ?? 2000);
  const [devices, setDevices] = useState(1);
  const [role, setRole] = useState('user');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const save = async (e) => {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const { data } = await axios.post('/api/admin/users', { username: username.trim() || null, password: password || null, daily_minutes: Number(minutes), monthly_minutes: Number(monthly), device_limit: devices, role });
      onCreated(data);
    } catch (err) { setError(errText(err)); setBusy(false); }
  };
  return (
    <Sheet title={tr('Add user')} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <input className={field} type="text" autoCapitalize="none" spellCheck={false} placeholder={tr('Username (leave empty to generate)')} value={username} onChange={(e) => setUsername(e.target.value)} />
        <input className={field} type="text" autoComplete="off" placeholder={tr('Password (leave empty to generate)')} value={password} onChange={(e) => setPassword(e.target.value)} minLength={password ? 8 : undefined} />
        <DevicePolicy value={devices} onChange={setDevices} />
        <label className="block text-xs text-ink-soft">{tr('Daily minutes')}<input className={`${field} mt-1`} type="number" min="0" value={minutes} onChange={(e) => setMinutes(e.target.value)} required /></label>
        <label className="block text-xs text-ink-soft">{tr('Monthly minutes')}<input className={`${field} mt-1`} type="number" min="0" value={monthly} onChange={(e) => setMonthly(e.target.value)} required /></label>
        {superadmin && <RolePicker value={role} onChange={setRole} />}
        {error && <p className="text-sm text-rose-500">{trs(error)}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className={btnGhost} onClick={onClose}>{tr('Cancel')}</button>
          <button className={btnPrimary} disabled={busy}>{tr('Create')}</button>
        </div>
      </form>
    </Sheet>
  );
}

function EditSheet({ user, me, superadmin, onClose, onSaved, onCredentials }) {
  const { tr, trs } = useI18n();
  const self = user.id === me;
  const [minutes, setMinutes] = useState(user.daily_minutes);
  const [monthly, setMonthly] = useState(user.monthly_minutes);
  const [status, setStatus] = useState(user.status || 'active');
  const [reason, setReason] = useState(user.status_reason || '');
  const [devices, setDevices] = useState(user.device_limit);
  const [role, setRole] = useState(user.is_admin ? 'admin' : 'user');
  const locked = !superadmin && user.is_superadmin && !self;   // only the owner can change the owner account
  const [list, setList] = useState(null);
  const [credit, setCredit] = useState(user.credit_minutes || 0);
  const [addMin, setAddMin] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const loadDevices = () => axios.get(`/api/admin/users/${user.id}/devices`).then((r) => setList(r.data.items)).catch((e) => setError(errText(e)));
  useEffect(() => { loadDevices(); }, []);

  const run = async (fn) => { setBusy(true); setError(''); try { await fn(); } catch (err) { setError(errText(err)); } finally { setBusy(false); } };
  const save = (e) => { e.preventDefault(); run(async () => {
    await axios.patch(`/api/admin/users/${user.id}`, { daily_minutes: Number(minutes), monthly_minutes: Number(monthly), status, status_reason: status === 'active' ? '' : reason, device_limit: devices, ...(superadmin && !user.is_superadmin ? { role } : {}) });
    onSaved();
  }); };
  const regenerate = () => { if (!window.confirm(tr('Make a new password? The old one stops working and the user is signed out everywhere.'))) return; run(async () => {
    const { data } = await axios.post(`/api/admin/users/${user.id}/reset-password`);
    onCredentials({ username: data.username, password: data.password });
  }); };
  const removeDevice = (d) => run(async () => { await axios.delete(`/api/admin/users/${user.id}/devices/${d.id}`); await loadDevices(); });
  const removeAll = () => { if (!window.confirm(tr('Sign this login out of all devices?'))) return; run(async () => { await axios.delete(`/api/admin/users/${user.id}/devices`); await loadDevices(); }); };

  return (
    <Sheet title={user.email} onClose={onClose}>
      <form onSubmit={save} className="space-y-3">
        <div>
          <p className="mb-1.5 text-xs text-ink-soft">{tr('Account status')}</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {['active', 'paused', 'deactivated', 'banned'].map((st) => (
              <button type="button" key={st} disabled={self && st !== 'active'} onClick={() => setStatus(st)}
                className={`rounded-2xl border px-2 py-2 text-xs capitalize disabled:opacity-40 ${status === st ? 'border-violet-400 bg-violet-500/30 text-ink' : 'border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{tr(st)}</button>
            ))}
          </div>
          <p className="mt-1.5 text-xs text-ink-faint">{tr(STATUS_HELP[status])}</p>
          {status !== 'active' && <input className={`${field} mt-2`} placeholder={tr('Reason (only you see it)')} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />}
        </div>
        <DevicePolicy value={devices} onChange={setDevices} />
        <label className="block text-xs text-ink-soft">{tr('Daily minutes')}<input className={`${field} mt-1`} type="number" min="0" value={minutes} onChange={(e) => setMinutes(e.target.value)} required /></label>
        <label className="block text-xs text-ink-soft">{tr('Monthly minutes')}<input className={`${field} mt-1`} type="number" min="0" value={monthly} onChange={(e) => setMonthly(e.target.value)} required /></label>
        {user.is_superadmin
          ? <p className="rounded-2xl bg-violet-500/10 px-3 py-2 text-xs text-violet-600">{tr('Superadmin (owner): sees everything, including Settings.')}</p>
          : superadmin && <RolePicker value={role} onChange={setRole} disabled={self} />}
        {locked && <p className="rounded-2xl bg-amber-500/10 px-3 py-2 text-xs text-amber-700">{tr('Only the owner (superadmin) can change the owner account.')}</p>}
        {self && <p className="text-xs text-ink-faint">{tr('You cannot disable or demote your own account.')}</p>}

        <div className="rounded-2xl border border-violet-100 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium">{tr('Devices')} <span className="text-xs text-ink-soft">({list ? list.length : '…'} / {devices === 0 ? tr('any') : devices})</span></p>
            {list && list.length > 0 && <button type="button" className="text-xs text-ink-soft hover:text-rose-600" onClick={removeAll} disabled={busy}>{tr('Remove all')}</button>}
          </div>
          {list && list.length === 0 && <p className="mt-2 text-xs text-ink-faint">{tr('No device has logged in yet.')}</p>}
          <ul className="mt-2 divide-y divide-violet-100">
            {(list || []).map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-2 py-2 text-xs">
                <div className="min-w-0"><p className="flex items-center gap-1.5 text-ink"><Monitor size={13} />{d.name || tr('Unknown device')}</p>
                  <p className="mt-0.5 text-ink-soft">{d.ip || '–'} · {tr('first')} {fmtTime(d.first_seen)} · {tr('last')} {fmtTime(d.last_seen)}</p></div>
                <button type="button" className="shrink-0 text-ink-soft hover:text-rose-600" aria-label={tr('Remove')} onClick={() => removeDevice(d)} disabled={busy}><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-ink-faint">{tr('A website cannot read the real device name, so the browser and system are shown. When the login is at its device limit, a new login signs out the device used longest ago. Removing a device signs it out.')}</p>
        </div>

        <div className="rounded-2xl border border-violet-100 p-3">
          <p className="text-sm font-medium">{tr('Bought minutes')}: <span className="text-violet-600">{credit} {tr('min')}</span></p>
          <div className="mt-2 flex gap-2">
            <input className={field} type="number" step="1" placeholder={tr('Minutes to add (negative takes back)')} value={addMin} onChange={(e) => setAddMin(e.target.value)} />
            <button type="button" className={btnGhost} disabled={busy || !Number(addMin)} onClick={() => run(async () => { const { data } = await axios.post(`/api/admin/users/${user.id}/credit`, { minutes: Number(addMin) }); setCredit(data.credit_minutes); setAddMin(''); })}>{tr('Add')}</button>
          </div>
        </div>
        <button type="button" className={`${btnGhost} w-full`} onClick={regenerate} disabled={busy}><KeyRound size={14} />{tr('Make a new password')}</button>
        {error && <p className="text-sm text-rose-500">{trs(error)}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" className={btnGhost} onClick={onClose}>{tr('Cancel')}</button>
          <button className={btnPrimary} disabled={busy}>{tr('Save')}</button>
        </div>
      </form>
    </Sheet>
  );
}

const FILTERS = ['', 'active', 'paused', 'deactivated', 'banned'];

export default function UsersPage({ me, superadmin, openJobsFor }) {
  const { tr } = useI18n();
  const [q, setQ] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(undefined); // undefined = closed, null = new user, object = edit
  const [creds, setCreds] = useState(null);
  const { data, error, loading, reload } = useApi(`/api/admin/users?q=${encodeURIComponent(query)}&page=${page}&status=${status}`, { every: 15000 });

  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(1); }, 300); return () => clearTimeout(t); }, [q]);
  const items = data?.items || [];
  const usage = (u) => tr('{used} / {limit} min', { used: u.used_minutes_today, limit: u.daily_minutes });
  const monthUsage = (u) => tr('{used} / {limit} min', { used: u.used_minutes_month ?? 0, limit: u.monthly_minutes });
  const pct = (u) => Math.min(100, u.daily_minutes ? (u.used_minutes_today / u.daily_minutes) * 100 : 100);
  const monthPct = (u) => Math.min(100, u.monthly_minutes ? ((u.used_minutes_month ?? 0) / u.monthly_minutes) * 100 : 100);
  const bar = (p) => <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full bg-violet-50"><div className={`h-full ${p > 90 ? 'bg-red-500 text-white' : 'bg-violet-500 text-white'}`} style={{ width: `${p}%` }} /></div>;
  const devLabel = (u) => (u.last_device ? `${u.last_device}` : tr('Never logged in'));
  const limitLabel = (u) => `${u.device_count} / ${u.device_limit === 0 ? tr('any') : u.device_limit}`;
  const Tags = ({ u }) => (<>
    {u.is_admin && <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] text-violet-600"><ShieldCheck size={11} />{tr(u.is_superadmin ? 'superadmin' : 'admin')}</span>}
    {u.status !== 'active' && <StatusChip status={u.status} />}
  </>);

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <div className="relative min-w-0 flex-1">
          <Search size={15} className="absolute left-3 top-2.5 text-ink-faint" />
          <input className={`${field} pl-9`} placeholder={tr('Search username…')} value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <button className={btnPrimary} onClick={() => setEditing(null)} aria-label={tr('Add user')}><Plus size={16} /><span className="hidden sm:inline">{tr('Add user')}</span></button>
      </div>
      <div className="mb-3 flex gap-2 overflow-x-auto">
        {FILTERS.map((f) => (
          <button key={f || 'all'} onClick={() => { setStatus(f); setPage(1); }}
            className={`shrink-0 rounded-full border px-3 py-1 text-xs ${status === f ? 'border-violet-400 bg-violet-500/30 text-ink' : 'border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{f ? tr(f) : tr('All')}</button>
        ))}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      <Card className="overflow-hidden !p-0">
        <table className="hidden w-full text-sm md:table">
          <thead className="bg-white text-left text-xs text-ink-soft">
            <tr><th className="px-4 py-3">{tr('Username')}</th><th className="px-4 py-3">{tr('Device')}</th><th className="px-4 py-3">{tr('IP')}</th><th className="px-4 py-3">{tr('Last seen')}</th><th className="px-4 py-3">{tr('Today')}</th><th className="px-4 py-3">{tr('This month')}</th><th className="px-4 py-3" /></tr>
          </thead>
          <tbody className="divide-y divide-violet-100">
            {items.map((u) => (
              <tr key={u.id} className="hover:bg-violet-50/40">
                <td className="px-4 py-3"><div className="flex flex-wrap items-center gap-2"><span className="break-all">{u.email}</span><Tags u={u} /></div>
                  {u.status_reason && u.status !== 'active' && <p className="mt-0.5 text-[11px] text-ink-faint">{u.status_reason}</p>}</td>
                <td className="px-4 py-3 text-ink-soft"><div>{devLabel(u)}</div><div className="text-[11px] text-ink-faint">{tr('devices')} {limitLabel(u)}</div></td>
                <td className="px-4 py-3 text-ink-soft">{u.last_ip || '–'}</td>
                <td className="px-4 py-3 text-ink-soft">{fmtTime(u.last_seen)}</td>
                <td className="px-4 py-3 text-ink-soft"><div>{usage(u)}</div>{bar(pct(u))}</td>
                <td className="px-4 py-3 text-ink-soft"><div>{monthUsage(u)}</div>{bar(monthPct(u))}</td>
                <td className="px-4 py-3"><div className="flex justify-end gap-2">
                  <button className={btnGhost} onClick={() => openJobsFor(u)}>{tr('Videos')}</button>
                  <button className={btnGhost} onClick={() => setEditing(u)}><Pencil size={14} />{tr('Manage')}</button>
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul className="divide-y divide-violet-100 md:hidden">
          {items.map((u) => (
            <li key={u.id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0"><div className="break-all text-sm font-medium">{u.email}</div><div className="mt-1 flex flex-wrap gap-1.5"><Tags u={u} /></div></div>
                <button className={btnGhost} onClick={() => setEditing(u)} aria-label={tr('Manage')}><Pencil size={14} /></button>
              </div>
              <div className="mt-2 space-y-1 text-xs text-ink-soft">
                <div>{devLabel(u)} · {u.last_ip || '–'} · {tr('devices')} {limitLabel(u)}</div>
                <div>{tr('Last seen')} {fmtTime(u.last_seen)}</div>
              </div>
              <div className="mt-2 flex items-end justify-between text-xs text-ink-soft">
                <div>{tr('Today')} {usage(u)}{bar(pct(u))}<div className="mt-1">{tr('This month')} {monthUsage(u)}</div></div>
                <button className="underline" onClick={() => openJobsFor(u)}>{tr('Videos')}</button>
              </div>
            </li>
          ))}
        </ul>
        {!items.length && <p className="p-6 text-center text-sm text-ink-faint">{loading ? tr('Loading…') : tr('No users found.')}</p>}
      </Card>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
      {editing === null && <CreateForm superadmin={superadmin} defaultMinutes={data?.default_daily_minutes} defaultMonthly={data?.default_monthly_minutes} onClose={() => setEditing(undefined)}
        onCreated={(u) => { setEditing(undefined); setCreds({ username: u.email, password: u.password }); reload(); }} />}
      {editing && <EditSheet key={editing.id} user={editing} me={me} superadmin={superadmin} onClose={() => setEditing(undefined)} onSaved={() => { setEditing(undefined); reload(); }}
        onCredentials={(c) => { setEditing(undefined); setCreds(c); reload(); }} />}
      {creds && <Credentials username={creds.username} password={creds.password} onClose={() => setCreds(null)} />}
    </div>
  );
}
