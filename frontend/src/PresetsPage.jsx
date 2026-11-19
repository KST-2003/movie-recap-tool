import React, { useCallback, useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';
import PresetEditor from './PresetEditor.jsx';

// "Presets": settings saved for new videos. The user keeps up to 5 of their own; presets made by the Recat team are listed too.
// "Use" opens the Create page with the preset applied (App.applyPreset).
function summary(s, tr) {
  const out = [];
  out.push(s.aspect && s.aspect !== 'original' ? s.aspect : tr('Original'));
  out.push(s.outputKind === 'subtitles' ? tr('Subtitles only') : s.outputKind === 'voice' ? tr('Voice-over only') : tr('Voice-over + subtitles'));
  out.push(s.voiceQuality === 'premium' ? tr('High quality voice') : tr('Standard voice'));
  if (s.filmMode === 'full') out.push(tr('Full movie / drama'));
  if (s.flip) out.push(tr('Flipped'));
  return out;
}

function PresetCard({ p, onUse, onEdit, onDelete, badge }) {
  const { tr } = useI18n();
  return (
    <div className="rounded-2xl border border-violet-100 bg-white p-4 shadow-card flex flex-col gap-3">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-ink break-words">{p.name}</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {badge && <span className="rounded-full bg-violet-500 px-2 py-0.5 text-[11px] font-semibold text-white">{badge}</span>}
            {summary(p.settings || {}, tr).map((t) => <span key={t} className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] text-ink-soft">{t}</span>)}
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={() => onUse(p)} className="flex-[2] rounded-2xl bg-violet-500 py-2 text-sm font-semibold text-white shadow-pop">{tr('Use this preset')}</button>
        {onEdit && <button type="button" onClick={() => onEdit(p)} className="flex-1 rounded-2xl border border-violet-200 bg-white py-2 text-sm font-semibold text-ink-soft">{tr('Edit')}</button>}
        {onDelete && <button type="button" onClick={() => onDelete(p)} className="rounded-2xl border border-rose-200 bg-white px-3 py-2 text-sm font-semibold text-rose-600">{tr('Delete')}</button>}
      </div>
    </div>
  );
}

export default function PresetsPage({ apiBase, onUse, active = true }) {
  const { tr, trs } = useI18n();
  const [data, setData] = useState(null);       // { max, mine, shared }
  const [editing, setEditing] = useState(null);  // null | 'new' | preset
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(() => axios.get(`${apiBase}/api/presets`).then((r) => setData(r.data)).catch(() => setData((previous) => previous || { max: 5, mine: [], shared: [] })), [apiBase]);
  useEffect(() => { if (active) load(); }, [load, active]);

  const save = async (name, settings) => {
    setSaving(true); setError('');
    try {
      if (editing === 'new') await axios.post(`${apiBase}/api/presets`, { name, settings });
      else await axios.put(`${apiBase}/api/presets/${editing.id}`, { name, settings });
      setEditing(null);
      await load();
    } catch (e) {
      const d = e.response?.data?.detail;
      setError(typeof d === 'string' && e.response.status < 500 ? trs(d) : tr('Could not save the preset. Please try again.'));
    } finally { setSaving(false); }
  };
  const remove = async (p) => {
    if (!window.confirm(tr('Delete the preset "{name}"?', { name: p.name }))) return;
    try { await axios.delete(`${apiBase}/api/presets/${p.id}`); await load(); } catch (e) { /* the list reloads below */ await load(); }
  };

  if (editing) {
    return (
      <div className="max-w-3xl mx-auto animate-rise">
        <h1 className="mb-4 text-2xl font-bold text-ink">{editing === 'new' ? tr('New preset') : tr('Edit preset')}</h1>
        <PresetEditor apiBase={apiBase} initial={editing === 'new' ? null : editing} saving={saving} error={error} onSave={save} onCancel={() => { setEditing(null); setError(''); }} />
      </div>
    );
  }
  const mine = data?.mine || [];
  const max = data?.max || 5;
  return (
    <div className="max-w-3xl mx-auto stagger space-y-6">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-ink">{tr('Presets')}</h1>
          <p className="text-sm text-ink-soft">{tr('Save your favourite settings once, then pick them with one tap when you make a new video.')}</p>
        </div>
        <button type="button" disabled={mine.length >= max} onClick={() => { setError(''); setEditing('new'); }}
          className="shrink-0 rounded-2xl bg-violet-500 px-4 py-2.5 text-sm font-semibold text-white shadow-pop disabled:opacity-40">+ {tr('New preset')}</button>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-ink">{tr('My presets')} <span className="font-normal text-ink-faint">{mine.length} / {max}</span></h2>
        {data && mine.length === 0 && <p className="rounded-2xl border border-dashed border-violet-200 bg-page p-6 text-center text-sm text-ink-soft">{tr('You have no presets yet. Press "New preset" to make one.')}</p>}
        {mine.length >= max && <p className="text-xs text-amber-700">{tr('You have 5 presets. Delete one to make a new one.')}</p>}
        <div className="grid gap-3 sm:grid-cols-2">
          {mine.map((p) => <PresetCard key={p.id} p={p} onUse={onUse} onEdit={(x) => { setError(''); setEditing(x); }} onDelete={remove} />)}
        </div>
      </section>

      {(data?.shared || []).length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-ink">{tr('Recat presets')}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {data.shared.map((p) => <PresetCard key={p.id} p={p} onUse={onUse} badge="Recat" />)}
          </div>
        </section>
      )}
    </div>
  );
}
