import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { ImagePlus, Pencil, Plus, Trash2 } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { errText, fmtTime, Card, Sheet, btnPrimary, btnGhost, field, Pager, useApi, ErrorBox } from './ui.jsx';

// Posts = the banners users see at the top of the app. Picture 16:9, a status (draft | published | off) and an optional schedule.
// "state" from the server says what users see right now: draft, scheduled, live, ended, off.
const API = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const STATE_STYLE = {
  live: 'bg-emerald-500/15 text-emerald-700', scheduled: 'bg-sky-500/15 text-sky-600', draft: 'bg-amber-500/15 text-amber-700',
  ended: 'bg-violet-300/20 text-ink-soft', off: 'bg-red-500/15 text-rose-600',
};
const STATUSES = [['draft', 'Draft', 'Saved, not shown to users.'], ['published', 'Published', 'Shown to users (inside the schedule, if one is set).'], ['off', 'Off', 'Hidden from users.']];
// <input type="datetime-local"> works in the admin's own time zone; the server stores UTC
const toLocal = (iso) => { if (!iso) return ''; const d = new Date(iso); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const toIso = (local) => (local ? new Date(local).toISOString() : '');

function PostForm({ post, onClose, onSaved }) {
  const { tr, trs } = useI18n();
  const [f, setF] = useState({ title: post?.title || '', body: post?.body || '', link_url: post?.link_url || '', status: post?.status || 'draft', starts: toLocal(post?.starts_at), ends: toLocal(post?.ends_at) });
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(post?.image_url ? `${API}${post.image_url}` : '');
  const [shape, setShape] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const pick = useRef(null);
  const set = (k) => (e) => setF((v) => ({ ...v, [k]: e.target.value }));
  useEffect(() => { if (!file) return undefined; const u = URL.createObjectURL(file); setPreview(u); return () => URL.revokeObjectURL(u); }, [file]);
  const wrongShape = shape && Math.abs(shape - 16 / 9) > 0.08;

  const save = async (e) => {
    e.preventDefault(); setBusy(true); setErr('');
    const fd = new FormData();
    fd.append('title', f.title); fd.append('body', f.body); fd.append('link_url', f.link_url); fd.append('status', f.status);
    fd.append('starts_at', toIso(f.starts)); fd.append('ends_at', toIso(f.ends));
    if (file) fd.append('image', file);
    try { await axios.post(post ? `/api/admin/posts/${post.id}` : '/api/admin/posts', fd); onSaved(); }
    catch (ex) { setErr(trs(errText(ex))); } finally { setBusy(false); }
  };

  return (
    <Sheet title={post ? tr('Edit post') : tr('New post')} onClose={onClose}>
      <form onSubmit={save} className="space-y-4 text-sm">
        <div>
          <button type="button" onClick={() => pick.current?.click()} className="group relative block aspect-video w-full overflow-hidden rounded-2xl border-2 border-dashed border-violet-200 bg-page">
            {preview
              ? <img src={preview} alt="" className="h-full w-full object-cover" onLoad={(e) => setShape(e.target.naturalWidth / e.target.naturalHeight)} />
              : <span className="flex h-full flex-col items-center justify-center gap-1 text-ink-faint"><ImagePlus size={26} /><span>{tr('Choose the banner picture')}</span></span>}
            {preview && <span className="absolute bottom-2 right-2 rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-ink shadow-card">{tr('Change picture')}</span>}
          </button>
          <input ref={pick} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => { setShape(null); setFile(e.target.files?.[0] || null); }} />
          <p className="mt-1 text-[11px] text-ink-faint">{tr('Wide picture, 16:9 (for example 1600 x 900). JPG, PNG or WEBP, up to 4 MB.')}</p>
          {wrongShape && <p className="mt-1 text-[11px] text-amber-700">{tr('This picture is not 16:9, so its edges will be cut off in the banner (the preview above shows how).')}</p>}
        </div>
        <label className="block"><span className="mb-1 block text-xs text-ink-soft">{tr('Title (only admins see it)')}</span>
          <input className={field} value={f.title} maxLength={120} required onChange={set('title')} /></label>
        <label className="block"><span className="mb-1 block text-xs text-ink-soft">{tr('Notes (optional, only admins see them)')}</span>
          <textarea className={field} rows={3} value={f.body} maxLength={600} onChange={set('body')} />
          <span className="mt-1 block text-[11px] text-ink-faint">{tr('The title and text are notes for the admin team only. Users see just the picture.')}</span></label>
        <label className="block"><span className="mb-1 block text-xs text-ink-soft">{tr('Link opened when the banner is tapped (optional)')}</span>
          <input className={field} type="url" placeholder="https://" value={f.link_url} maxLength={500} onChange={set('link_url')} /></label>
        <div>
          <span className="mb-1 block text-xs text-ink-soft">{tr('Status')}</span>
          <div className="grid grid-cols-3 gap-2">
            {STATUSES.map(([k, label]) => (
              <button key={k} type="button" aria-pressed={f.status === k} onClick={() => setF((v) => ({ ...v, status: k }))}
                className={`rounded-2xl border px-2 py-2 text-xs font-medium ${f.status === k ? 'border-violet-500 bg-violet-500 text-white shadow-pop' : 'border-violet-200 text-ink-soft hover:bg-violet-50'}`}>{tr(label)}</button>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-ink-faint">{tr(STATUSES.find(([k]) => k === f.status)[2])}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block"><span className="mb-1 block text-xs text-ink-soft">{tr('Show from (empty = right away)')}</span>
            <input className={field} type="datetime-local" value={f.starts} onChange={set('starts')} /></label>
          <label className="block"><span className="mb-1 block text-xs text-ink-soft">{tr('Show until (empty = no end)')}</span>
            <input className={field} type="datetime-local" value={f.ends} onChange={set('ends')} /></label>
        </div>
        <p className="text-[11px] text-ink-faint">{tr('Times are in your own time zone. The schedule only counts while the status is Published.')}</p>
        {err && <p className="rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-600">{err}</p>}
        <button className={`${btnPrimary} w-full`} disabled={busy}>{busy ? tr('Saving…') : tr('Save post')}</button>
      </form>
    </Sheet>
  );
}

export default function PostsPage() {
  const { tr, trs } = useI18n();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState(null);   // null | 'new' | post
  const [err, setErr] = useState('');
  const { data, error, loading, reload } = useApi(`/api/admin/posts?page=${page}`, { every: 60000 });
  const items = data?.items || [];
  const remove = async (p) => {
    if (!window.confirm(tr('Delete the post "{t}"? This cannot be undone.', { t: p.title }))) return;
    setErr('');
    try { await axios.delete(`/api/admin/posts/${p.id}`); await reload(); } catch (e) { setErr(trs(errText(e))); }
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 flex-1 text-sm text-ink-soft">{tr('Posts are the banner pictures users swipe through at the top of the app. Only posts marked "live" are shown.')}</p>
        <button className={btnPrimary} onClick={() => setEditing('new')}><Plus size={16} />{tr('New post')}</button>
      </div>
      <ErrorBox error={error} onRetry={reload} />
      {err && <p className="mb-2 text-sm text-rose-500">{err}</p>}
      <div className="stagger grid gap-3 md:grid-cols-2">
        {items.map((p) => (
          <Card key={p.id} className="overflow-hidden !p-0">
            <div className="relative aspect-video w-full bg-page">
              {p.image_url ? <img src={`${API}${p.image_url}`} alt="" className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center text-xs text-ink-faint">{tr('No picture yet')}</span>}
              <span className={`absolute left-3 top-3 rounded-full bg-white px-2.5 py-0.5 text-[11px] font-semibold shadow-card`}><span className={`rounded-full px-1.5 ${STATE_STYLE[p.state]}`}>{tr(p.state)}</span></span>
            </div>
            <div className="p-4 text-sm">
              <p className="break-words font-semibold">{p.title}</p>
              {p.body && <p className="mt-1 line-clamp-2 break-words text-xs text-ink-soft">{p.body}</p>}
              {p.link_url && <a href={p.link_url} target="_blank" rel="noreferrer" className="mt-1 block truncate text-xs text-violet-600 underline">{p.link_url}</a>}
              <p className="mt-2 text-[11px] text-ink-faint">{p.starts_at ? tr('From {t}', { t: fmtTime(p.starts_at) }) : tr('From: right away')} · {p.ends_at ? tr('until {t}', { t: fmtTime(p.ends_at) }) : tr('no end')}</p>
              <p className="text-[11px] text-ink-faint">{p.created_by} · {fmtTime(p.created_at)}</p>
              <div className="mt-3 flex gap-2">
                <button className={`${btnGhost} flex-1`} onClick={() => setEditing(p)}><Pencil size={14} />{tr('Edit')}</button>
                <button className={btnGhost} aria-label={tr('Delete')} onClick={() => remove(p)}><Trash2 size={14} /></button>
              </div>
            </div>
          </Card>
        ))}
      </div>
      {!items.length && <p className="p-6 text-center text-sm text-ink-faint">{loading ? tr('Loading…') : tr('No posts yet. Make the first one with "New post".')}</p>}
      {data && data.total > data.per_page && <Pager page={data.page} perPage={data.per_page} total={data.total} onPage={setPage} />}
      {editing && <PostForm post={editing === 'new' ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); reload(); }} />}
    </div>
  );
}
