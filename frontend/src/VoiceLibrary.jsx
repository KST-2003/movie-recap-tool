import React, { useMemo, useState } from 'react';
import { useI18n } from './i18n.jsx';

const CATS = ['all', 'female', 'male', 'age', 'creature', 'machine', 'animal', 'mood'];

// Full-screen "see more" page: every Gemini voice plus the character looks, with category chips and a search box.
export default function VoiceLibrary({ voices, looks, selected, playing, onPlay, onSelect, onClose, apiBase }) {
  const { tr } = useI18n();
  const [cat, setCat] = useState('all');
  const [q, setQ] = useState('');

  const items = useMemo(() => [
    ...voices.map((v) => ({ key: v.name, kind: 'voice', cat: v.gender, title: v.name, sub: `${v.gender} · Gemini voice`, sample_url: v.sample_url, voice: v })),
    ...looks.map((l) => ({ key: `look:${l.id}`, kind: 'look', cat: l.group, title: l.label, sub: `${l.group} · ${l.voice}`, sample_url: l.sample_url })),
  ], [voices, looks]);

  const shown = items.filter((it) => (cat === 'all' || it.cat === cat)
    && (!q.trim() || `${it.title} ${it.sub} ${it.cat}`.toLowerCase().includes(q.trim().toLowerCase())));
  const count = (c) => items.filter((it) => c === 'all' || it.cat === c).length;

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 overflow-y-auto">
      <div className="max-w-5xl mx-auto px-3 sm:px-4 py-4">
        <div className="sticky top-0 bg-slate-950 pb-3 z-10">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-3">
            <button type="button" onClick={onClose} className="px-3 py-1.5 rounded-lg bg-slate-800 text-sm">← {tr('Back')}</button>
            <h2 className="text-base sm:text-lg font-bold text-purple-300 min-w-0 break-words">{tr('All voices')}</h2>
            <span className="text-xs text-slate-500 ml-auto whitespace-nowrap">{tr('{n} shown', { n: shown.length })}</span>
          </div>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr('Search: name, female, old, monster, cat…')}
            className="w-full min-w-0 text-ellipsis rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm outline-none focus:border-purple-500" />
          <div className="flex gap-1.5 mt-2 overflow-x-auto pb-1">
            {CATS.map((c) => (
              <button key={c} type="button" onClick={() => setCat(c)}
                className={`shrink-0 px-3 py-1 rounded-full text-xs font-semibold ${cat === c ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-300'}`}>
                {tr(c === 'all' ? 'All' : c)} <span className="opacity-60">{count(c)}</span>
              </button>
            ))}
          </div>
        </div>
        {shown.length === 0 && <p className="text-sm text-slate-500 py-8 text-center">{tr('Nothing found.')}</p>}
        <div className="grid grid-cols-1 min-[420px]:grid-cols-2 md:grid-cols-4 gap-2">
          {shown.map((it) => (
            <div key={it.key} className={`p-2 min-w-0 rounded-xl border ${it.kind === 'voice' && selected === it.key ? 'border-purple-500 bg-purple-950/40' : 'border-slate-800 bg-slate-800/50'}`}>
              <div className="font-semibold text-sm break-words leading-snug">{it.kind === 'look' ? tr(it.title) : it.title}</div>
              <div className="text-xs text-slate-400 capitalize break-words leading-snug">{it.sub}</div>
              <div className="flex items-center gap-2 mt-2 text-xs whitespace-nowrap">
                <button type="button" onClick={() => onPlay({ name: it.key, sample_url: it.sample_url })} className="text-purple-300 hover:text-white whitespace-nowrap">
                  {playing === it.key ? tr('■ Stop') : tr('▶ Play')}
                </button>
                <a href={`${apiBase}${it.sample_url}`} download className="text-slate-400 hover:text-white">⬇</a>
                {it.kind === 'voice'
                  ? <button type="button" onClick={() => { onSelect(it.voice); onClose(); }} className="ml-auto px-2 py-0.5 rounded-full bg-purple-600 text-white">{tr('Use')}</button>
                  : <span className="ml-auto text-[10px] text-slate-500">{tr('for characters')}</span>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
