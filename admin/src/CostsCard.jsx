import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, field, useApi } from './ui.jsx';

// Real cost from token counts: Google's USD prices per 1M tokens (editable) x the USD->THB rate. History is re-priced when a price changes.
const FIELDS = [['in', 'Text in'], ['out', 'Text out'], ['audio_out', 'Voice out'], ['chars', 'Characters']];
const n = (v) => Number(v || 0).toLocaleString('en-US', { maximumFractionDigits: 1 });

export default function CostsCard({ onSaved }) {
  const { tr } = useI18n();
  const { data, error, reload } = useApi('/api/admin/costs');
  const [rate, setRate] = useState('');
  const [prices, setPrices] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  useEffect(() => { if (data) { setRate(String(data.usd_thb)); setPrices(JSON.parse(JSON.stringify(data.prices))); } }, [data]);
  if (!data) return error ? <p className="text-sm text-rose-600">{errText({ response: { data: { detail: error } } })}</p> : null;

  const set = (model, key, v) => setPrices((p) => ({ ...p, [model]: { ...(p[model] || {}), [key]: v === '' ? undefined : Number(v) } }));
  const save = async () => {
    setBusy(true); setMsg('');
    try { await axios.put('/api/admin/settings', { usd_thb: Number(rate), prices }); await reload(); onSaved?.(); setMsg(tr('Prices saved. Past videos were re-priced.')); }
    catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  };
  const unpriced = data.models.filter((m) => !m.priced).map((m) => m.model);

  return (
    <Card title={tr('Real cost (from token counts)')}>
      <p className="mb-3 text-sm text-ink-soft">{tr("Every video's Gemini / Claude token counts are saved and priced with the USD prices below (per 1M tokens, from Google's pricing page) x the exchange rate. Check the prices again when Google changes them (the 3.8 models double on 2027-01-01).")}</p>
      <div className="mb-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-2xl bg-violet-50/60 p-3"><div className="text-xs text-ink-soft">{tr('Measured cost per video minute')}</div>
          <div className="mt-0.5 text-lg font-semibold">{data.measured_cost_per_minute != null ? `${data.measured_cost_per_minute} THB` : '–'}</div>
          <div className="text-[11px] text-ink-faint">{data.measured_cost_per_minute != null ? tr('last 30 finished videos') : tr('needs 3 finished videos; using {c} THB', { c: data.configured_cost_per_minute })}</div></div>
        <div className="rounded-2xl bg-violet-50/60 p-3"><div className="text-xs text-ink-soft">{tr('Counted cost, last 30 days')}</div><div className="mt-0.5 text-lg font-semibold">{n(data.total_thb_30d)} THB</div></div>
        <label className="rounded-2xl bg-violet-50/60 p-3 text-xs text-ink-soft">{tr('THB per 1 USD')}<input className={`${field} mt-1`} type="number" min="1" step="0.1" value={rate} onChange={(e) => setRate(e.target.value)} /></label>
      </div>
      {unpriced.length > 0 && <p className="mb-3 rounded-2xl bg-amber-500/10 p-3 text-sm text-amber-700">{tr('No price for: {m}. Videos using them are priced only in part, so the budget falls back to the estimate. Add the price below.', { m: unpriced.join(', ') })}</p>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-xs">
          <thead className="text-left text-ink-soft"><tr><th className="py-1.5 pr-2">{tr('Model')}</th><th className="px-2">{tr('Calls')}</th><th className="px-2">{tr('Tokens in / out / voice')}</th><th className="px-2">THB</th>
            {FIELDS.map(([k, l]) => <th key={k} className="px-2">{tr(l)} $/1M</th>)}</tr></thead>
          <tbody className="divide-y divide-violet-100">
            {data.models.map((m) => (
              <tr key={m.model} className={m.priced ? '' : 'bg-amber-500/5'}>
                <td className="py-1.5 pr-2 break-all">{m.model}{data.assumed.includes(m.model) && <span className="ml-1 text-amber-700" title={tr('Assumed equal to the AI Studio price: check Cloud pricing')}>*</span>}{m.est > 0 && <span className="ml-1 text-ink-faint" title={tr('voice tokens estimated from clip length')}>~</span>}</td>
                <td className="px-2">{n(m.calls)}</td>
                <td className="px-2 text-ink-soft">{n(m.in + m.audio_in)} / {n(m.out)} / {n(m.audio_out)}{m.chars > 0 && ` · ${n(m.chars)} ${tr('chars')}`}</td>
                <td className="px-2">{n(m.thb)}</td>
                {FIELDS.map(([k]) => <td key={k} className="px-2"><input className={`${field} !px-2 !py-1 w-20`} type="number" min="0" step="0.01" value={prices[m.model]?.[k] ?? ''} onChange={(e) => set(m.model, k, e.target.value)} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-sm text-ink-soft">{msg}</span>
        <button className={btnPrimary} disabled={busy || !rate} onClick={save}>{tr('Save prices')}</button>
      </div>
      {data.recent.length > 0 && (
        <div className="mt-4">
          <div className="mb-1 text-xs text-ink-soft">{tr('Latest videos')}</div>
          <ul className="divide-y divide-violet-100 text-xs">
            {data.recent.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-x-3 py-1.5">
                <span className="w-28 text-ink-soft">{fmtTime(j.created_at)}</span>
                <span className="text-ink-soft">{j.edit ? tr('re-render') : tr('{n} min video', { n: j.minutes })}</span>
                <span className="ml-auto text-ink">{j.cost_thb} THB{!j.complete ? ' *' : ''}{j.estimated ? ' ~' : ''}</span>
                {j.minutes > 0 && <span className="w-24 text-right text-ink-faint">{(j.cost_thb / j.minutes).toFixed(2)} {tr('THB/min')}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
