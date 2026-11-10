import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';

// Pay as you go: pick a pack, pay the owner's QR, send the slip. The owner checks it and adds the minutes by hand.
const thb = (n) => `${Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 })} THB`;
const when = (iso) => new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const STATUS = { pending: 'bg-amber-900/50 text-amber-300', approved: 'bg-emerald-900/50 text-emerald-300', rejected: 'bg-red-900/50 text-red-300' };

export default function TopUpPage({ apiBase, onChanged }) {
  const { tr, trs } = useI18n();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [pack, setPack] = useState(null);
  const [slip, setSlip] = useState(null);
  const [preview, setPreview] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const load = () => axios.get(`${apiBase}/api/topup`).then((r) => { setInfo(r.data); setError(''); }).catch((e) => setError(trs(e.response?.data?.detail) || e.message));
  useEffect(() => { load(); }, [apiBase]);
  useEffect(() => {
    if (!slip || !slip.type.startsWith('image/')) { setPreview(''); return undefined; }
    const url = URL.createObjectURL(slip);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [slip]);

  const submit = async (e) => {
    e.preventDefault();
    if (!pack || !slip) return;
    setBusy(true); setError(''); setSent(false);
    const form = new FormData();
    form.append('minutes', pack.minutes);
    form.append('note', note);
    form.append('slip', slip);
    try {
      await axios.post(`${apiBase}/api/topup/requests`, form);
      setSent(true); setSlip(null); setNote(''); setPack(null);
      await load(); onChanged?.();
    } catch (err) { setError(trs(err.response?.data?.detail) || err.message); } finally { setBusy(false); }
  };

  if (error && !info) return <div className="max-w-3xl mx-auto p-4 rounded-xl bg-red-950/50 border border-red-800 text-red-300 text-sm">{error}</div>;
  if (!info) return <div className="max-w-3xl mx-auto text-sm text-slate-400 p-4">{tr('Loading…')}</div>;

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div>
        <h2 className="text-xl font-bold text-white">{tr('Top up minutes')}</h2>
        <p className="mt-1 text-xs text-slate-400">
          {tr('Your bought minutes: {n} min.', { n: info.credit_minutes })} {tr('They are used only after your daily or monthly allowance is used up, and they do not expire.')}
        </p>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">{tr('1. Choose minutes')}</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {info.packs.map((p) => (
            <button key={p.minutes} type="button" onClick={() => setPack(p)}
              className={`rounded-xl border p-3 text-left ${pack?.minutes === p.minutes ? 'border-purple-500 bg-purple-950/40' : 'border-slate-700 bg-slate-800/50 hover:bg-slate-800'}`}>
              <span className="block text-lg font-semibold text-white">{p.minutes} <span className="text-xs font-normal text-slate-400">{tr('min')}</span></span>
              <span className="block text-sm text-purple-300">{thb(p.price_thb)}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">{tr('{price} per video minute.', { price: thb(info.price_per_minute) })}</p>
      </div>

      <form onSubmit={submit} className="rounded-xl border border-slate-800 bg-slate-900 p-4 space-y-3">
        <h3 className="text-sm font-semibold text-slate-200">{tr('2. Pay with the QR code')}</h3>
        {info.qr_url ? (
          <div className="flex flex-col items-center gap-2">
            <img src={`${apiBase}${info.qr_url}`} alt={tr('Payment QR code')} className="w-56 max-w-full rounded-xl bg-white p-2" />
            {pack && <p className="text-sm text-white">{tr('Pay exactly {amount} for {n} minutes.', { amount: thb(pack.price_thb), n: pack.minutes })}</p>}
            {info.payment_note && <p className="text-xs text-slate-400 whitespace-pre-line text-center">{info.payment_note}</p>}
          </div>
        ) : (
          <p className="text-sm text-amber-300">{tr('Top-up is not set up yet. Please ask the admin.')}</p>
        )}
        <h3 className="text-sm font-semibold text-slate-200 pt-1">{tr('3. Send your payment slip')}</h3>
        <input type="file" accept="image/*,application/pdf" onChange={(e) => setSlip(e.target.files?.[0] || null)}
          className="block w-full text-xs text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-700 file:px-3 file:py-2 file:text-slate-100" />
        {preview && <img src={preview} alt="" className="max-h-48 rounded-lg border border-slate-700" />}
        <input className="w-full rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-purple-500" maxLength={300}
          placeholder={tr('Note for the admin (optional)')} value={note} onChange={(e) => setNote(e.target.value)} />
        {error && <p className="text-sm text-red-400">{error}</p>}
        {sent && <p className="text-sm text-emerald-300">{tr('Sent. The admin will check your slip and add your minutes.')}</p>}
        <button disabled={busy || !pack || !slip || !info.qr_url} className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-500 font-semibold disabled:opacity-50">
          {busy ? tr('Sending…') : tr('Send slip')}
        </button>
      </form>

      <div className="rounded-xl border border-slate-800 bg-slate-900 p-4">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">{tr('Your top-ups')}</h3>
        {info.requests.length === 0 ? <p className="text-sm text-slate-400">{tr('No top-ups yet.')}</p> : (
          <ul className="divide-y divide-slate-800">
            {info.requests.map((r) => (
              <li key={r.id} className="py-2 text-xs">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span className="text-slate-300 w-32">{when(r.created_at)}</span>
                  <span className="text-slate-100">{r.minutes} {tr('min')} · {thb(r.amount_thb)}</span>
                  <span className={`ml-auto px-2 py-0.5 rounded-full ${STATUS[r.status]}`}>{tr(r.status)}</span>
                </div>
                {r.admin_note && <p className="mt-1 text-red-300">{tr('Reason')}: {r.admin_note}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
