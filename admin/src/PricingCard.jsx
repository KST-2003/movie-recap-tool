import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';
import { errText, Card, btnPrimary, btnGhost, field, useApi } from './ui.jsx';

// Pay as you go: the price per video minute, the minute packs users can buy, the payment QR, and how the price compares with our real cost.
const API = import.meta.env.VITE_API_BASE || '';
const thb = (n) => `${Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })} THB`;

export default function PricingCard({ settings, onSaved }) {
  const { tr, trs } = useI18n();
  const { data, reload } = useApi('/api/admin/pricing');
  const [price, setPrice] = useState('');
  const [packs, setPacks] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const fileRef = useRef(null);
  useEffect(() => { if (settings) { setPrice(String(settings.price_per_minute_thb)); setPacks(settings.topup_packs.join(', ')); setNote(settings.payment_note || ''); } }, [settings]);
  if (!data) return null;

  const run = async (fn, ok) => { setBusy(true); setMsg(''); try { await fn(); await reload(); onSaved?.(); setMsg(ok); } catch (e) { setMsg(trs(errText(e))); } finally { setBusy(false); } };
  const save = () => run(() => axios.put('/api/admin/settings', {
    price_per_minute_thb: Number(price), topup_packs: packs.split(/[ ,]+/).filter(Boolean).map(Number), payment_note: note,
  }), tr('Pricing saved.'));
  const upload = (e) => {
    const f = e.target.files?.[0]; e.target.value = '';
    if (!f) return;
    const form = new FormData(); form.append('file', f);
    run(() => axios.post('/api/admin/payment-qr', form), tr('QR code saved.'));
  };
  const priceNum = Number(price) || 0;
  const bad = !(priceNum > 0) || packs.split(/[ ,]+/).filter(Boolean).some((m) => !(Number(m) >= 1));

  return (
    <Card title={tr('Pricing & payment (pay as you go)')}>
      <p className="mb-3 text-sm text-slate-400">{tr('Users buy video minutes. They pay by the QR code below and send you the slip; you check it on the Top-ups page and the minutes are added. Bought minutes are used only after a user\'s daily or monthly allowance is used up.')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs text-slate-400">{tr('Price per video minute (THB)')}<input className={`${field} mt-1`} type="number" min="0.01" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} /></label>
        <label className="block text-xs text-slate-400">{tr('Minute packs (comma separated)')}<input className={`${field} mt-1`} value={packs} onChange={(e) => setPacks(e.target.value)} placeholder="30, 60, 100, 200" /></label>
      </div>
      <label className="mt-3 block text-xs text-slate-400">{tr('Note shown next to the QR (account name, what to write on the transfer...)')}
        <textarea className={`${field} mt-1`} rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></label>

      <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800">
        <table className="w-full text-sm">
          <thead className="bg-slate-900 text-left text-xs text-slate-400"><tr><th className="px-3 py-2">{tr('Pack')}</th><th className="px-3 py-2">{tr('Users pay')}</th>
            <th className="px-3 py-2">{tr('Our cost (High quality)')}</th><th className="px-3 py-2">{tr('Our cost (Standard)')}</th></tr></thead>
          <tbody className="divide-y divide-slate-800">
            {packs.split(/[ ,]+/).filter((m) => Number(m) >= 1).map((m) => (
              <tr key={m}><td className="px-3 py-2">{m} {tr('min')}</td><td className="px-3 py-2">{thb(Number(m) * priceNum)}</td>
                <td className="px-3 py-2 text-slate-300">{thb(Number(m) * data.cost_per_minute.premium)}</td><td className="px-3 py-2 text-slate-300">{thb(Number(m) * data.cost_per_minute.standard)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
        {['premium', 'standard'].map((q) => {
          const margin = priceNum > 0 ? Math.round(((priceNum - data.cost_per_minute[q]) / priceNum) * 1000) / 10 : null;
          return (
            <div key={q} className="rounded-xl bg-slate-800/60 px-3 py-2">
              <dt>{q === 'premium' ? tr('High quality') : tr('Standard')}: {tr('cost per video minute')} {thb(data.cost_per_minute[q])} {data.cost_measured[q] ? tr('(measured)') : tr('(estimate, set in Budget)')}</dt>
              <dd className={`mt-0.5 text-sm ${margin == null ? '' : margin < 50 ? 'text-amber-300' : 'text-emerald-300'}`}>{tr('Margin')}: {margin == null ? '–' : `${margin}%`}</dd>
            </div>
          );
        })}
      </dl>
      <p className="mt-2 text-[11px] text-slate-500">{tr('Margin = (price - cost) / price, before payment fees. Google says the Gemini 3.8 prices double on 2027-01-01: check the margin again then.')}</p>

      <div className="mt-4 rounded-xl border border-slate-800 p-3">
        <p className="mb-2 text-sm font-medium">{tr('Payment QR code')}</p>
        {data.qr_url ? <img src={`${API}${data.qr_url}`} alt="QR" className="mb-2 max-h-56 rounded-lg bg-white p-2" /> : <p className="mb-2 text-xs text-amber-300">{tr('No QR yet: users cannot top up until you upload one.')}</p>}
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={upload} />
        <div className="flex gap-2">
          <button className={btnGhost} disabled={busy} onClick={() => fileRef.current?.click()}>{data.qr_url ? tr('Replace QR') : tr('Upload QR (screenshot)')}</button>
          {data.qr_url && <button className={btnGhost} disabled={busy} onClick={() => run(() => axios.delete('/api/admin/payment-qr'), tr('QR code removed.'))}>{tr('Remove')}</button>}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-3">
        {msg && <span className="text-xs text-slate-300">{msg}</span>}
        <button className={btnPrimary} disabled={busy || bad} onClick={save}>{tr('Save pricing')}</button>
      </div>
    </Card>
  );
}
