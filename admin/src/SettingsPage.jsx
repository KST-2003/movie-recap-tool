import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';
import { errText, Card, btnPrimary, btnGhost, field, Toggle, useApi, ErrorBox, Loading } from './ui.jsx';

export default function SettingsPage() {
  const { tr, trs } = useI18n();
  const { data, error, reload } = useApi('/api/admin/settings');
  const [cap, setCap] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [confirm, setConfirm] = useState(false);
  useEffect(() => { if (data) setCap(String(data.global_daily_minutes)); }, [data]);
  if (!data) return error ? <ErrorBox error={error} onRetry={reload} /> : <Loading />;

  const save = async (patch, ok) => {
    setBusy(true); setMsg('');
    try { await axios.put('/api/admin/settings', patch); await reload(); setMsg(ok); } catch (e) { setMsg(trs(errText(e))); } finally { setBusy(false); setConfirm(false); }
  };
  const rows = [
    [tr('Sign-ups open'), data.allow_signup ? tr('yes') : tr('no')], [tr('Default daily minutes'), data.default_daily_minutes],
    [tr('Longest video'), tr('{n} min', { n: data.max_video_minutes })], [tr('Largest upload'), `${data.max_upload_mb} MB`],
    [tr('Active videos per user'), data.max_active_jobs_per_user], [tr('Queue'), data.queue_mode],
  ];
  return (
    <div className="space-y-4">
      <Card title={tr('Maintenance mode')}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-slate-400">{tr('When on, new videos and re-renders are refused with a "try again later" message. Running videos finish.')}</p>
          <Toggle checked={data.maintenance} disabled={busy} onChange={(v) => (v ? setConfirm(true) : save({ maintenance: false }, tr('Maintenance mode is off.')))} />
        </div>
        {confirm && (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl bg-amber-500/10 p-3 text-sm text-amber-200">
            <span className="flex-1">{tr('Stop accepting new videos for everyone?')}</span>
            <button className={btnGhost} onClick={() => setConfirm(false)}>{tr('Cancel')}</button>
            <button className={btnPrimary} disabled={busy} onClick={() => save({ maintenance: true }, tr('Maintenance mode is on.'))}>{tr('Turn on')}</button>
          </div>
        )}
      </Card>
      <Card title={tr('Global daily ceiling (minutes of video, all users)')}>
        <p className="mb-3 text-sm text-slate-400">{tr("Protects the API bill: once today's total reaches this, new videos are refused. 0 = unlimited.")}</p>
        <div className="flex gap-2">
          <input className={field} type="number" min="0" value={cap} onChange={(e) => setCap(e.target.value)} />
          <button className={btnPrimary} disabled={busy || cap === '' || Number(cap) === data.global_daily_minutes} onClick={() => save({ global_daily_minutes: Number(cap) }, tr('Ceiling saved.'))}>{tr('Save')}</button>
        </div>
      </Card>
      {msg && <p className="text-sm text-slate-300">{msg}</p>}
      <Card title={tr('Server limits (edit backend/.env, then restart)')}>
        <dl className="divide-y divide-slate-800 text-sm">
          {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-3 py-2"><dt className="text-slate-400">{k}</dt><dd className="text-right">{String(v)}</dd></div>)}
        </dl>
      </Card>
    </div>
  );
}
