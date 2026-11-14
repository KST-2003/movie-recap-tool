import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';

// "My videos": every video the user made. The list is kept; the video file only for the keeping time (the owner sets the days).
const KIND = { recap: 'Recap voice-over', full: 'Full movie voice-over', subtitles: 'Subtitles only', edit: 'Edit / re-render' };
const fmt = (n) => (Math.round(n * 10) / 10).toLocaleString('en-US', { maximumFractionDigits: 1 });
const when = (iso) => new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const daysLeft = (iso) => Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000));

export default function HistoryPage({ apiBase, refreshKey, onOpen }) {
  const { tr, trs } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState('');

  const load = () => axios.get(`${apiBase}/api/jobs?page=${page}&per_page=15`)
    .then((r) => { setData(r.data); setError(''); })
    .catch((e) => setError(trs(e.response?.data?.detail) || e.message));
  useEffect(() => { load(); }, [apiBase, refreshKey, page]);

  const remove = async (job) => {
    if (!window.confirm(tr('Delete this video and its files now? This cannot be undone.'))) return;
    setBusy(job.id);
    try { await axios.delete(`${apiBase}/api/jobs/${job.id}`); await load(); }
    catch (e) { setError(trs(e.response?.data?.detail) || e.message); }
    finally { setBusy(''); }
  };

  if (error && !data) return <div className="max-w-4xl mx-auto p-4 rounded-2xl bg-rose-50/50 border border-rose-200 text-rose-600 text-sm">{error}</div>;
  if (!data) return <div className="max-w-4xl mx-auto text-sm text-ink-soft p-4">{tr('Loading…')}</div>;
  const pages = Math.max(1, Math.ceil(data.total / data.per_page));

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <div>
        <h2 className="text-xl font-bold text-ink">{tr('My videos')}</h2>
        <p className="mt-1 text-xs text-ink-soft">
          {tr('Finished videos are kept for {n} days, then removed to save space. The list stays.', { n: data.keep_result_days })}{' '}
          {tr('You can edit a video for {n} days after you uploaded it.', { n: data.keep_source_days })}
        </p>
      </div>
      {error && <div className="p-3 rounded-2xl bg-rose-50/50 border border-rose-200 text-rose-600 text-sm">{error}</div>}
      {data.items.length === 0 ? (
        <div className="rounded-2xl border border-violet-100 bg-white p-6 text-sm text-ink-soft">{tr('No videos yet.')}</div>
      ) : (
        <ul className="space-y-3">
          {data.items.map((j) => {
            const ok = j.status === 'done';
            const left = j.expires_at ? daysLeft(j.expires_at) : null;
            return (
              <li key={j.id} className="rounded-2xl border border-violet-100 bg-white p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-ink">{j.title || tr('Untitled video')}</p>
                    <p className="mt-0.5 text-xs text-ink-soft">
                      {when(j.created_at)} · {tr(KIND[j.kind] || j.kind)} · {fmt(j.minutes)} {tr('min')} · {j.aspect === 'original' ? tr('Original') : j.aspect}
                    </p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${ok ? 'bg-emerald-50/50 text-emerald-700' : j.status === 'error' ? 'bg-rose-100/50 text-rose-600' : 'bg-violet-50 text-ink-soft'}`}>
                    {ok ? '✓ ' : j.status === 'error' ? '✕ ' : ''}{tr(j.status)}
                  </span>
                </div>
                {j.error && <p className="mt-2 text-xs text-rose-600">{trs(j.error)}</p>}
                {ok && (
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    {j.video_available ? (
                      <>
                        <button type="button" onClick={() => onOpen(j.id)} className="rounded-lg bg-violet-500 px-3 py-1.5 text-xs font-semibold hover:bg-violet-600 text-white">
                          {j.can_edit ? tr('Open & edit') : tr('Open')}
                        </button>
                        <span className={`text-xs ${left <= 3 ? 'text-amber-700' : 'text-ink-soft'}`}>
                          {left <= 1 ? tr('Removed within a day: download it now') : tr('Kept for {n} more days', { n: left })}
                        </span>
                      </>
                    ) : (
                      <span className="text-xs text-ink-soft">{tr('The video was removed after its keeping time. Upload the original again to make a new one.')}</span>
                    )}
                    <button type="button" disabled={busy === j.id} onClick={() => remove(j)} className="ml-auto text-xs text-ink-soft hover:text-rose-600 disabled:opacity-50">{tr('Delete')}</button>
                  </div>
                )}
                {!ok && j.status !== 'running' && j.status !== 'queued' && (
                  <div className="mt-3 flex"><button type="button" disabled={busy === j.id} onClick={() => remove(j)} className="ml-auto text-xs text-ink-soft hover:text-rose-600">{tr('Delete')}</button></div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-xs text-ink-soft">
          <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-lg bg-violet-50 px-3 py-1.5 disabled:opacity-40">‹</button>
          <span>{page} / {pages}</span>
          <button type="button" disabled={page >= pages} onClick={() => setPage(page + 1)} className="rounded-lg bg-violet-50 px-3 py-1.5 disabled:opacity-40">›</button>
        </div>
      )}
    </div>
  );
}
