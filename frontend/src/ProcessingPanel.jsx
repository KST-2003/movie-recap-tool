import React from 'react';
import { useI18n } from './i18n.jsx';

const STEPS = [
  { label: 'Uploading your video', from: -1, to: 0 },
  { label: 'Finding subtitles and scene cuts', from: 0, to: 10 },
  { label: 'Transcribing and translating to Burmese', from: 10, to: 30 },
  { label: 'Shortening long lines to fit their scenes', from: 30, to: 35 },
  { label: 'Generating the Burmese voice-over', from: 35, to: 62 },
  { label: 'Fitting each line to its scene', from: 62, to: 75 },
  { label: 'Rendering the final video', from: 75, to: 100 },
];
const mmss = (t) => `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`;

// What is done, what is running now, what is left, so a long job never looks stuck.
export default function ProcessingPanel({ upload, progress, elapsed, subsOnly }) {
  const { tr, trs } = useI18n();
  const uploading = upload !== null && upload < 100;
  const pct = uploading ? -1 : progress.pct;
  return (
    <div className="w-full max-w-xs mt-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
      <div className="flex justify-between text-slate-400 mb-2">
        <span>{tr('Working on your video')}</span>
        <span className="font-mono">{mmss(elapsed)}</span>
      </div>
      <ol className="space-y-1.5">
        {STEPS.map((st, i) => (subsOnly && i >= 3 && i <= 5 ? null : (st && { st, i }))).filter(Boolean).map(({ st, i }) => {
          const done = i === 0 ? !uploading : pct >= st.to;
          const active = !done && (i === 0 ? uploading : pct >= st.from && pct < st.to);
          return (
            <li key={st.label} className="flex items-start gap-2">
              <span className={`mt-0.5 w-4 h-4 flex-shrink-0 rounded-full flex items-center justify-center text-[10px] ${
                done ? 'bg-emerald-500 text-slate-900' : active ? 'border-2 border-purple-400 border-t-transparent animate-spin' : 'border border-slate-600'
              }`}>{done ? '✓' : ''}</span>
              <span className={done ? 'text-slate-400' : active ? 'text-white' : 'text-slate-500'}>
                {tr(st.label)}
                {active && <span className="block text-purple-300">{i === 0 ? `${upload}%` : trs(progress.stage)}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-[11px] text-slate-500">{tr('Longer videos can take a few minutes. You can cancel at any time.')}</p>
    </div>
  );
}
