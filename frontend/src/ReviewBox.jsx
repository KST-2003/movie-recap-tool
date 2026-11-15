import React, { useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';

// Optional rating under a finished video: 5 stars + a few words. Only the admins read it. "Not now" hides it for this video.
const skipKey = (id) => `review_skip_${id}`;
export const reviewSkipped = (id) => { try { return localStorage.getItem(skipKey(id)) === '1'; } catch (e) { return false; } };

export default function ReviewBox({ apiBase, jobId, onClose }) {
  const { tr } = useI18n();
  const [stars, setStars] = useState(0);
  const [hover, setHover] = useState(0);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const skip = () => { try { localStorage.setItem(skipKey(jobId), '1'); } catch (e) { /* optional */ } onClose(); };
  const submit = async () => {
    if (!stars || busy) return;
    setBusy(true); setError('');
    try { await axios.post(`${apiBase}/api/jobs/${jobId}/review`, { stars, text: text.trim() }); setDone(true); }
    catch (e) { setError(tr('We could not complete this just now. Our team has been notified. Please try again a little later.')); }
    finally { setBusy(false); }
  };

  if (done) {
    return (
      <div className="w-full max-w-md rounded-2xl border border-violet-100 bg-white p-5 text-center shadow-card animate-rise">
        <img src="/recat-thanks.webp" alt="" aria-hidden="true" draggable={false} className="mx-auto h-40 w-40 select-none object-contain animate-pop" />
        <p className="mt-2 text-lg font-bold text-ink">{tr('Thank You for Feedback!')}</p>
        <button type="button" onClick={onClose} className="mt-3 rounded-full bg-violet-50 px-4 py-1.5 text-xs font-medium text-ink-soft hover:bg-violet-100">{tr('Close')}</button>
      </div>
    );
  }
  const shown = hover || stars;
  return (
    <div className="w-full max-w-md rounded-2xl border border-violet-100 bg-white p-4 text-left shadow-card animate-rise">
      <p className="text-sm font-semibold text-ink">{tr('How was this video?')}</p>
      <p className="mt-0.5 text-xs text-ink-soft">{tr('Your rating helps us improve. It is optional.')}</p>
      <div className="mt-3 flex justify-center gap-1.5" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" onClick={() => setStars(n)} onMouseEnter={() => setHover(n)} aria-label={tr('{n} stars', { n })} aria-pressed={stars === n}
            className="p-1 transition-transform active:scale-90 hover:scale-110">
            <svg viewBox="0 0 24 24" className={`h-9 w-9 ${n <= shown ? 'fill-amber-400 text-amber-400' : 'fill-transparent text-violet-200'}`} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
              <path d="M12 2.6l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5L2.6 9.4l6.5-.9z" />
            </svg>
          </button>
        ))}
      </div>
      <textarea value={text} onChange={(e) => setText(e.target.value.slice(0, 1000))} rows={3} placeholder={tr('Tell us more (optional)')}
        className="mt-3 w-full rounded-2xl border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-ink outline-none focus:border-violet-400" />
      {error && <p className="mt-1 text-xs text-rose-600">{error}</p>}
      <div className="mt-3 flex items-center justify-end gap-2">
        <button type="button" onClick={skip} className="rounded-full px-3 py-1.5 text-xs font-medium text-ink-soft hover:bg-violet-50">{tr('Not now')}</button>
        <button type="button" onClick={submit} disabled={!stars || busy} className="rounded-full bg-violet-500 px-5 py-1.5 text-sm font-semibold text-white hover:bg-violet-600 disabled:opacity-40">{tr('Submit')}</button>
      </div>
    </div>
  );
}
