import React, { useState } from 'react';
import axios from 'axios';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, btnPrimary, btnGhost, useApi, ErrorBox } from './ui.jsx';
import PresetEditor from './preset/PresetEditor.jsx';

// Presets made here are for EVERYBODY: "Draft" = only admins see it, "Submitted" (published) = every user finds it under Presets / the
// Preset button on the Create page. Users keep their own presets (max 5) separately; admins cannot see those.
const BADGE = { draft: 'bg-amber-500/15 text-amber-700', published: 'bg-emerald-500/15 text-emerald-700' };

function summary(s, tr) {
  const out = [s.aspect && s.aspect !== 'original' ? s.aspect : tr('Original')];
  out.push(s.outputKind === 'subtitles' ? tr('Subtitles only') : s.outputKind === 'voice' ? tr('Voice-over only') : tr('Voice-over + subtitles'));
  out.push(s.voiceQuality === 'premium' ? tr('High quality voice') : tr('Standard voice'));
  if (s.filmMode === 'full') out.push(tr('Full movie / drama'));
  if (s.flip) out.push(tr('Flipped'));
  return out;
}

export default function PresetsPage() {
  const { tr, trs } = useI18n();
  const [editing, setEditing] = useState(null);   // null | 'new' | preset
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const { data, error, loading, reload } = useApi('/api/admin/presets', { every: 60000 });
  const items = data?.items || [];

  const save = async (name, settings, status) => {
    setSaving(true); setErr('');
    try {
      if (editing === 'new') await axios.post('/api/admin/presets', { name, settings, status });
      else await axios.put(`/api/admin/presets/${editing.id}`, { name, settings, status });
      setEditing(null); await reload();
    } catch (e) { setErr(trs(errText(e))); } finally { setSaving(false); }
  };
  const setStatus = async (p, status) => {
    setErr('');
    try { await axios.put(`/api/admin/presets/${p.id}`, { name: p.name, settings: p.settings, status }); await reload(); } catch (e) { setErr(trs(errText(e))); }
  };
  const remove = async (p) => {
    if (!window.confirm(tr('Delete the preset "{t}"? Users will not see it any more.', { t: p.name }))) return;
    setErr('');
    try { await axios.delete(`/api/admin/presets/${p.id}`); await reload(); } catch (e) { setErr(trs(errText(e))); }
  };

  if (editing) {
    return (
      <div className="mx-auto max-w-3xl">
        <h2 className="mb-4 text-lg font-semibold">{editing === 'new' ? tr('New preset') : tr('Edit preset')}</h2>
        <PresetEditor admin initial={editing === 'new' ? null : editing} saving={saving} error={err} onSave={save} onCancel={() => { setEditing(null); setErr(''); }} />
      </div>
    );
  }
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm text-ink-soft">{tr('Presets made here are for everybody. Users see only the ones you Submit; drafts stay with the admins. Users can also keep up to 5 presets of their own.')}</p>
        <button className={btnPrimary} onClick={() => { setErr(''); setEditing('new'); }}><Plus size={16} />{tr('New preset')}</button>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {err && <p className="mb-2 text-sm text-rose-500">{err}</p>}
      <div className="stagger grid gap-3 md:grid-cols-2">
        {items.map((p) => (
          <Card key={p.id}>
            <div className="flex items-start gap-2">
              <p className="min-w-0 flex-1 break-words font-semibold">{p.name}</p>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${BADGE[p.status]}`}>{p.status === 'published' ? tr('Submitted') : tr('Draft')}</span>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {summary(p.settings || {}, tr).map((t) => <span key={t} className="rounded-full bg-violet-50 px-2 py-0.5 text-[11px] text-ink-soft">{t}</span>)}
            </div>
            <p className="mt-2 text-[11px] text-ink-faint">{p.created_by} · {fmtTime(p.updated_at || p.created_at)}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className={btnPrimary} onClick={() => setStatus(p, p.status === 'published' ? 'draft' : 'published')}>
                {p.status === 'published' ? tr('Withdraw (back to draft)') : tr('Submit to users')}
              </button>
              <button className={`${btnGhost} flex-1`} onClick={() => { setErr(''); setEditing(p); }}><Pencil size={14} />{tr('Edit')}</button>
              <button className={btnGhost} aria-label={tr('Delete')} onClick={() => remove(p)}><Trash2 size={14} /></button>
            </div>
          </Card>
        ))}
      </div>
      {!items.length && <p className="p-6 text-center text-sm text-ink-faint">{loading ? tr('Loading…') : tr('No presets yet. Make the first one with "New preset".')}</p>}
    </div>
  );
}
