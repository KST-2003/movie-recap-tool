import React, { useState } from 'react';
import { useI18n } from './i18n.jsx';
import { fmtTime, Card, Pager, useApi, ErrorBox, Loading, Stat } from './ui.jsx';

// What users said about their videos (optional 1-5 stars + words, asked after a video is made). Admins only.
const Stars = ({ n, size = 'h-4 w-4' }) => (
  <span className="inline-flex gap-0.5" aria-label={`${n} / 5`}>
    {[1, 2, 3, 4, 5].map((i) => (
      <svg key={i} viewBox="0 0 24 24" className={`${size} ${i <= n ? 'fill-amber-400 text-amber-400' : 'fill-transparent text-violet-200'}`} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
        <path d="M12 2.6l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z" />
      </svg>
    ))}
  </span>
);

export default function ReviewsPage() {
  const { tr } = useI18n();
  const [stars, setStars] = useState(0);
  const [page, setPage] = useState(1);
  const { data, error, loading, reload } = useApi(`/api/admin/reviews?page=${page}${stars ? `&stars=${stars}` : ''}`, { every: 30000 });
  if (error && !data) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const most = Math.max(1, ...Object.values(data.by_stars));
  const kind = (v) => [tr(v.output === 'subtitles' ? 'Subtitles only' : v.mode === 'full' ? 'Full movie' : 'Recap'), tr(v.voice_quality === 'standard' ? 'Standard voice' : 'High quality voice'),
    tr(v.device_render ? 'made on the device' : 'made on the server'), `${v.minutes} ${tr('min')}`, v.aspect === 'original' ? tr('Original') : v.aspect, v.resolution ? `${v.resolution}p` : '', v.from_link ? tr('from a link') : '']
    .filter(Boolean).join(' · ');
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label={tr('Average rating')} value={data.average != null ? `${data.average.toFixed(2)} / 5` : '–'} />
        <Stat label={tr('Reviews')} value={data.count} />
        <Card>
          <div className="space-y-1">
            {Object.entries(data.by_stars).sort((a, b) => b[0] - a[0]).map(([n, c]) => (
              <div key={n} className="flex items-center gap-2 text-xs text-ink-soft">
                <span className="w-7 shrink-0">{n} ★</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-violet-50"><div className="h-full rounded-full bg-amber-400" style={{ width: `${(c / most) * 100}%` }} /></div>
                <span className="w-7 shrink-0 text-right">{c}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {[0, 5, 4, 3, 2, 1].map((n) => (
          <button key={n} type="button" onClick={() => { setStars(n); setPage(1); }}
            className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-medium ${stars === n ? 'bg-violet-500 text-white' : 'border border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{n ? `${n} ★` : tr('All')}</button>
        ))}
      </div>
      {data.items.length === 0 ? (
        <Card><p className="text-sm text-ink-soft">{tr('No reviews yet.')}</p></Card>
      ) : (
        <ul className="space-y-3">
          {data.items.map((r) => (
            <li key={r.id} className="rounded-2xl border border-violet-100 bg-white p-4 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-3">
                  <Stars n={r.stars} />
                  <span className="text-sm font-semibold text-ink">{r.user.email || `#${r.user.id}`}</span>
                  {r.user.deleted && <span className="rounded-full bg-rose-500/10 px-2 py-0.5 text-[11px] text-rose-600">{tr('account deleted')}</span>}
                </div>
                <span className="text-xs text-ink-faint">{fmtTime(r.created_at)}</span>
              </div>
              {r.text ? <p className="mt-2 whitespace-pre-wrap break-words text-sm text-ink">{r.text}</p> : <p className="mt-2 text-xs text-ink-faint">{tr('No words, stars only.')}</p>}
              <div className="mt-3 rounded-2xl bg-violet-50 px-3 py-2 text-xs text-ink-soft">
                {r.video ? (
                  <>
                    <p className="truncate font-medium text-ink">{r.video.title || tr('Untitled video')} <span className="font-mono font-normal text-ink-faint">· {r.video.id}</span></p>
                    <p className="mt-0.5">{kind(r.video)}{r.video.run_seconds ? ` · ${tr('took {n} s', { n: Math.round(r.video.run_seconds) })}` : ''} · {fmtTime(r.video.created_at)}{r.video.deleted ? ` · ${tr('deleted by the user')}` : ''}</p>
                  </>
                ) : <p>{tr('The video record no longer exists.')}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
      <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />
    </div>
  );
}
