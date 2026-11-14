import React, { useState } from 'react';
import axios from 'axios';
import { Check, X } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, btnGhost, field, Pager, useApi, ErrorBox } from './ui.jsx';

// Payment slips waiting for you: open the slip, compare the amount with your bank, then approve (adds the minutes) or reject.
const API = import.meta.env.VITE_API_BASE || '';
const STYLE = { pending: 'bg-amber-500/15 text-amber-700', approved: 'bg-emerald-500/15 text-emerald-700', rejected: 'bg-red-500/15 text-rose-600' };
const FILTERS = ['pending', 'approved', 'rejected', ''];

export default function TopupsPage({ onChanged }) {
  const { tr, trs } = useI18n();
  const [status, setStatus] = useState('pending');
  const [page, setPage] = useState(1);
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(0);
  const [err, setErr] = useState('');
  const { data, error, loading, reload } = useApi(`/api/admin/topups?status=${status}&page=${page}`, { every: 20000 });
  const items = data?.items || [];

  const decide = async (id, kind, body) => {
    setBusy(id); setErr('');
    try { await axios.post(`/api/admin/topups/${id}/${kind}`, body); setRejecting(null); setReason(''); await reload(); onChanged?.(); }
    catch (e) { setErr(trs(errText(e))); } finally { setBusy(0); }
  };
  const isPdf = (u) => /\.pdf\?/.test(u || '');

  return (
    <div>
      <div className="mb-3 flex gap-2 overflow-x-auto">
        {FILTERS.map((f) => (
          <button key={f || 'all'} onClick={() => { setStatus(f); setPage(1); }}
            className={`shrink-0 rounded-full border px-3 py-1 text-xs ${status === f ? 'border-violet-400 bg-violet-500/30 text-ink' : 'border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{f ? tr(f) : tr('All')}</button>
        ))}
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {err && <p className="mb-2 text-sm text-rose-500">{err}</p>}
      <div className="space-y-3">
        {items.map((r) => (
          <Card key={r.id}>
            <div className="flex flex-wrap items-start gap-4">
              {r.slip_url && (isPdf(r.slip_url)
                ? <a className={btnGhost} href={`${API}${r.slip_url}`} target="_blank" rel="noreferrer">{tr('Open slip (PDF)')}</a>
                : <a href={`${API}${r.slip_url}`} target="_blank" rel="noreferrer"><img src={`${API}${r.slip_url}`} alt="slip" className="h-40 w-28 rounded-lg border border-violet-200 object-cover" /></a>)}
              <div className="min-w-0 flex-1 text-sm">
                <p className="break-all font-medium">{r.email}</p>
                <p className="mt-1 text-lg font-semibold">{r.minutes} {tr('min')} · {Number(r.amount_thb).toLocaleString('en-US')} THB</p>
                <p className="text-xs text-ink-soft">{fmtTime(r.created_at)} · {r.price_per_minute} THB/{tr('min')}</p>
                {r.note && <p className="mt-1 text-xs text-ink-soft">“{r.note}”</p>}
                <span className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[11px] ${STYLE[r.status]}`}>{tr(r.status)}</span>
                {r.status !== 'pending' && <p className="mt-1 text-xs text-ink-faint">{r.decided_by} · {fmtTime(r.decided_at)}{r.admin_note ? ` · ${r.admin_note}` : ''}</p>}
              </div>
              {r.status === 'pending' && (
                <div className="flex w-full flex-col gap-2 sm:w-48">
                  <button className={btnPrimary} disabled={busy === r.id} onClick={() => { if (window.confirm(tr('Add {n} minutes to {email}? Check that the slip amount matches {amount} THB.', { n: r.minutes, email: r.email, amount: r.amount_thb }))) decide(r.id, 'approve'); }}><Check size={15} />{tr('Approve + add minutes')}</button>
                  {rejecting === r.id ? (
                    <>
                      <input className={field} placeholder={tr('Reason (the user sees it)')} value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
                      <button className={btnGhost} disabled={busy === r.id} onClick={() => decide(r.id, 'reject', { reason })}><X size={15} />{tr('Confirm reject')}</button>
                    </>
                  ) : <button className={btnGhost} onClick={() => setRejecting(r.id)}><X size={15} />{tr('Reject')}</button>}
                </div>
              )}
            </div>
          </Card>
        ))}
        {!items.length && <p className="p-6 text-center text-sm text-ink-faint">{loading ? tr('Loading…') : tr('No top-ups here.')}</p>}
      </div>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
    </div>
  );
}
