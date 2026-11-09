import React, { useState } from 'react';
import axios from 'axios';
import { CheckCircle2, XCircle, RefreshCw } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { STATUS_STYLE, Card, Stat, btnGhost, errText, useApi, ErrorBox, Loading } from './ui.jsx';

// Raw rows Google Cloud returned (unmatched), to check by eye why a model has no real limit/usage above
function GoogleRaw() {
  const { tr } = useI18n();
  const [open, setOpen] = useState(false);
  if (!open) return <button className={btnGhost} onClick={() => setOpen(true)}>{tr('Show what Google returns')}</button>;
  return <GoogleRawBody onHide={() => setOpen(false)} />;
}

function GoogleRawBody({ onHide }) {
  const { tr } = useI18n();
  const { data, error } = useApi('/api/admin/google-quota');   // only fetched while the panel is open
  const rows = data?.limits ? data : null;
  return (
    <Card title={tr('What Google Cloud returned (unmatched)')} action={<button className="text-xs text-slate-400 underline" onClick={onHide}>{tr('Hide')}</button>}>
      <p className="mb-3 text-xs text-slate-500">{tr("If a model's real limit is missing above, look for its name in the dimensions or labels here.")}</p>
      <ErrorBox error={error || data?.error} />
      {!rows ? <Loading /> : (
        <div className="space-y-4">
          <div>
            <h3 className="mb-1 text-xs font-semibold text-slate-300">{tr('Request limits')}</h3>
            <ul className="max-h-72 divide-y divide-slate-800 overflow-y-auto rounded-xl bg-slate-950/50 text-xs">
              {rows.limits.map((r, i) => (
                <li key={i} className="px-3 py-2">
                  <div className="break-all text-slate-200">{r.metric.replace('generativelanguage.googleapis.com/', '')}</div>
                  <div className="break-all text-slate-500">{r.unit} · {Object.entries(r.dimensions).map(([k, v]) => `${k}=${v}`).join(', ') || tr('default')} · <span className="text-purple-300">{r.limit ?? '?'}</span></div>
                </li>
              ))}
              {!rows.limits.length && <li className="px-3 py-2 text-slate-500">{tr('No rows.')}</li>}
            </ul>
          </div>
          <div>
            <h3 className="mb-1 text-xs font-semibold text-slate-300">{tr('Usage since midnight Pacific')}</h3>
            <ul className="max-h-72 divide-y divide-slate-800 overflow-y-auto rounded-xl bg-slate-950/50 text-xs">
              {rows.usage.map((u, i) => (
                <li key={i} className="px-3 py-2">
                  <div className="break-all text-slate-200">{u.quota_metric.replace('generativelanguage.googleapis.com/', '') || '?'} · <span className="text-purple-300">{u.used}</span></div>
                  <div className="break-all text-slate-500">{Object.entries(u.labels).filter(([k]) => k !== 'quota_metric').map(([k, v]) => `${k}=${v}`).join(', ')}</div>
                </li>
              ))}
              {!rows.usage.length && <li className="px-3 py-2 text-slate-500">{tr('No rows.')}</li>}
            </ul>
          </div>
        </div>
      )}
    </Card>
  );
}

export default function TtsPage() {
  const { tr } = useI18n();
  const { data, error, reload } = useApi('/api/admin/tts', { every: 15000 });
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState('');
  if (!data) return error ? <ErrorBox error={error} onRetry={reload} /> : <Loading />;

  const total = data.models.reduce((a, m) => a + m.per_day, 0);
  const left = data.models.reduce((a, m) => a + m.remaining, 0);
  const fmtLeft = (s) => tr('{h}h {m}m', { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60) });
  const checkNow = async () => {
    setChecking(true); setCheckError('');
    try { await axios.get('/api/admin/tts?refresh=true'); await reload(); } catch (e) { setCheckError(errText(e)); } finally { setChecking(false); }
  };
  const cloud = data.cloud;

  return (
    <div className="space-y-4">
      <ErrorBox error={error || checkError} onRetry={reload} />
      {data.all_blocked && <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{tr('Every voice model is out of requests: new videos with a voice-over are refused until a limit resets.')}</div>}

      <Card title={tr('Google connection')} action={
        <button className={`${btnGhost} !px-2.5 !py-1.5`} disabled={checking} onClick={checkNow}><RefreshCw size={14} className={checking ? 'animate-spin' : ''} />{checking ? tr('Checking…') : tr('Check with Google now')}</button>}>
        <ul className="space-y-1.5 text-sm">
          <li className="flex items-start gap-2">
            {data.verify_error ? <XCircle size={16} className="mt-0.5 flex-shrink-0 text-red-400" /> : <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0 text-emerald-400" />}
            <span className="min-w-0 break-words text-slate-300">{data.verify_error ? tr('Could not check the models with your API key: {e}', { e: data.verify_error }) : tr('API key works: models are checked against Google.')}</span>
          </li>
          <li className="flex items-start gap-2">
            {cloud.configured && !cloud.error ? <CheckCircle2 size={16} className="mt-0.5 flex-shrink-0 text-emerald-400" /> : <XCircle size={16} className={`mt-0.5 flex-shrink-0 ${cloud.configured ? 'text-red-400' : 'text-slate-500'}`} />}
            <span className="min-w-0 break-words text-slate-300">
              {!cloud.configured ? tr("Google Cloud is not connected, so limits and usage below are what this server configured and counted itself. To show Google's real numbers, set GCP_PROJECT_ID and GCP_SERVICE_ACCOUNT_FILE in backend/.env (see .env.example).")
                : cloud.error ? tr('Google Cloud (project {p}): {e}', { p: cloud.project, e: cloud.error }) : tr('Google Cloud connected (project {p}): real limits and usage are shown.', { p: cloud.project })}
            </span>
          </li>
        </ul>
      </Card>

      <div className="grid grid-cols-2 gap-3">
        <Stat label={tr('Requests left today')} value={left} sub={tr('of {n} (all models)', { n: total })} />
        <Stat label={tr('Quota day (Pacific)')} value={data.day.slice(5)} sub={tr('resets at midnight PT')} />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {data.models.map((m) => {
          const c = m.cloud;
          const realLimit = c?.per_day_limit ?? m.seen_limit?.per_day ?? null;   // Google's own number, whichever source has it
          const differs = realLimit != null && realLimit !== m.per_day;
          const limit = c?.per_day_limit ?? m.per_day;
          const used = c?.used_today ?? m.used_today;
          const pct = limit ? Math.min(100, (used / limit) * 100) : 100;
          const blocked = m.blocked_seconds > 0;
          const state = blocked ? ['blocked', 'error'] : m.remaining === 0 ? ['exhausted', 'cancelled'] : ['available', 'done'];
          const seen = m.seen_limit && [m.seen_limit.per_day != null ? tr('{n}/day', { n: m.seen_limit.per_day }) : null, m.seen_limit.per_minute != null ? tr('{n}/min', { n: m.seen_limit.per_minute }) : null].filter(Boolean).join(' · ');
          return (
            <Card key={m.model}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 break-all text-sm font-medium">{m.model}</div>
                <span className={`inline-block flex-shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[state[1]]}`}>{tr(state[0])}</span>
              </div>
              {blocked && <div className="mt-0.5 text-[11px] text-slate-500">{tr('Google refused it, resets in {t}', { t: fmtLeft(m.blocked_seconds) })}</div>}
              {m.google && (
                <div className={`mt-1 flex items-start gap-1.5 text-xs ${m.google.exists ? 'text-emerald-400' : 'text-red-400'}`}>
                  {m.google.exists ? <CheckCircle2 size={14} className="mt-px flex-shrink-0" /> : <XCircle size={14} className="mt-px flex-shrink-0" />}
                  <span className="min-w-0 break-words">{m.google.exists ? tr('Exists for your API key · {i} in / {o} out tokens', { i: m.google.input_token_limit, o: m.google.output_token_limit }) : tr('Not found for your API key: requests to this model will fail')}</span>
                </div>
              )}
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800"><div className={`h-full ${pct > 90 ? 'bg-red-500' : 'bg-purple-500'}`} style={{ width: `${pct}%` }} /></div>
              <div className="mt-1.5 flex justify-between gap-2 text-xs text-slate-400">
                <span>{tr('{used} / {limit} today', { used, limit })}{c?.used_today != null && c.used_today !== m.used_today ? ` · ${tr('this server counted {n}', { n: m.used_today })}` : ''}</span>
                <span className="flex-shrink-0">{tr('{n}/min', { n: c?.per_minute_limit ?? m.per_minute })}</span>
              </div>
              <dl className="mt-3 space-y-1 border-t border-slate-800 pt-2 text-[11px] text-slate-500">
                <div className="flex justify-between gap-2"><dt>{tr('Configured here (TTS_MODELS)')}</dt><dd className="text-right">{tr('{n}/day', { n: m.per_day })} · {tr('{n}/min', { n: m.per_minute })}</dd></div>
                {seen && <div className="flex justify-between gap-2"><dt>{tr('Google said when it refused')}</dt><dd className="text-right">{seen}</dd></div>}
                {c && <div className="flex justify-between gap-2"><dt>{tr('Google Cloud limit')}</dt><dd className="text-right">{c.per_day_limit != null || c.per_minute_limit != null ? [c.per_day_limit != null ? tr('{n}/day', { n: c.per_day_limit }) : null, c.per_minute_limit != null ? tr('{n}/min', { n: c.per_minute_limit }) : null].filter(Boolean).join(' · ') : tr('not found')}</dd></div>}
              </dl>
              {c?.ambiguous && <p className="mt-2 text-[11px] text-amber-300">{tr('Several different limits matched (free + paid tier?): the biggest is shown. Check the raw data below.')}</p>}
              {differs && <p className="mt-2 text-[11px] text-amber-300">{tr("Google's real limit ({n}/day) differs from the one configured here. Update TTS_MODELS in backend/.env so quotas are counted correctly.", { n: realLimit })}</p>}
            </Card>
          );
        })}
      </div>
      {cloud.configured && <GoogleRaw />}
      <p className="text-xs text-slate-500">{tr("Counts come from this server's own tally (data/tts_usage.json) plus Google's refusals; Google's dashboard is the source of truth.")}</p>
    </div>
  );
}
