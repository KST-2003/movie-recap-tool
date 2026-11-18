import React, { useState } from 'react';
import axios from 'axios';
import { Check, X } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, btnGhost, field, Pager, useApi, ErrorBox } from './ui.jsx';

// Users paused after 5 failed / cancelled videos in a row who ask to continue. Look at their last failures (is it OUR fault?), then approve
// (uploads open at once, the earlier failures stop counting) or reject (they stay paused until the 3 hours end and see your reason).
const STYLE = { pending: 'bg-amber-500/15 text-amber-700', approved: 'bg-emerald-500/15 text-emerald-700', rejected: 'bg-red-500/15 text-rose-600' };
const FILTERS = ['pending', 'approved', 'rejected', ''];

export default function UnlockPage({ onChanged }) {
  const { tr, trs } = useI18n();
  const [status, setStatus] = useState('pending');
  const [page, setPage] = useState(1);
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(0);
  const [err, setErr] = useState('');
  const { data, error, loading, reload } = useApi(`/api/admin/unlock-requests?status=${status}&page=${page}`, { every: 20000 });
  const items = data?.items || [];

  const decide = async (id, kind, body) => {
    setBusy(id); setErr('');
    try { await axios.post(`/api/admin/unlock-requests/${id}/${kind}`, body); setRejecting(null); setReason(''); await reload(); onChanged?.(); }
    catch (e) { setErr(trs(errText(e))); } finally { setBusy(0); }
  };

  return (
    <div>
      <p className="mb-3 text-sm text-ink-soft">{tr('These users failed or cancelled 5 videos in a row, so uploads are paused for 3 hours. Check their last videos below: if the failures were our fault (server or Google problem), approve to let them continue now.')}</p>
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
              <div className="min-w-0 flex-1 text-sm">
                <p className="break-all font-medium">{r.email}</p>
                <p className="text-xs text-ink-soft">{fmtTime(r.created_at)}</p>
                {r.note && <p className="mt-1 text-sm">“{r.note}”</p>}
                <span className={`mt-2 inline-block rounded-full px-2 py-0.5 text-[11px] ${STYLE[r.status]}`}>{tr(r.status)}</span>
                {r.status === 'pending' && !r.still_paused && <span className="ml-2 text-xs text-ink-faint">{tr('The pause already ended.')}</span>}
                {r.status !== 'pending' && <p className="mt-1 text-xs text-ink-faint">{r.decided_by} · {fmtTime(r.decided_at)}{r.admin_note ? ` · ${r.admin_note}` : ''}</p>}
                <p className="mt-3 text-xs font-medium text-ink-soft">{tr('Last failed or cancelled videos')}</p>
                <ul className="mt-1 space-y-1">
                  {r.failures.map((f) => (
                    <li key={f.id} className="rounded-lg bg-violet-50 px-2 py-1 text-xs">
                      <span className="font-medium">{tr(f.status === 'error' ? 'Failed' : 'Cancelled')}</span> · {fmtTime(f.finished_at)}
                      {f.error && <span className="block break-words text-ink-soft">{f.error}</span>}
                    </li>
                  ))}
                  {!r.failures.length && <li className="text-xs text-ink-faint">–</li>}
                </ul>
              </div>
              {r.status === 'pending' && (
                <div className="flex w-full flex-col gap-2 sm:w-48">
                  <button className={btnPrimary} disabled={busy === r.id} onClick={() => { if (window.confirm(tr('Let {email} upload videos again now?', { email: r.email }))) decide(r.id, 'approve'); }}><Check size={15} />{tr('Approve: let them continue')}</button>
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
        {!items.length && <p className="p-6 text-center text-sm text-ink-faint">{loading ? tr('Loading…') : tr('No requests here.')}</p>}
      </div>
      {data && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
    </div>
  );
}
