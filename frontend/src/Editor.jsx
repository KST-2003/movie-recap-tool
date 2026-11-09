import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useI18n } from './i18n.jsx';

const TEMPOS = [null, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5];
const DEFAULT_MODEL = { a: 0.16, b: 0.7 };

// Same formula as backend/duration_model.py: seconds a voice needs for a line, predicted without calling the TTS.
export function syllables(text) {
  let n = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    if (c >= 0x1000 && c <= 0x1021 && (i === 0 || text[i - 1] !== '\u1039') && !(i + 1 < text.length && text[i + 1] === '\u103a')) n += 1;
    else if (c >= 0x1023 && c <= 0x1027) n += 1;
  }
  if (n === 0) n = Math.max(1, Math.round([...text].filter((ch) => /[a-z0-9]/i.test(ch)).length / 3));
  return n;
}
// one colour per character (timeline blocks, badges): [normal, selected/active edge]
const PALETTE = ['#7c3aed', '#0891b2', '#d97706', '#db2777', '#059669', '#2563eb', '#dc2626', '#65a30d'];
const MIN_LEN = 0.2; // shortest a line may be, seconds
const fmt = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

/**
 * CapCut-mobile style timeline for a finished job. The timeline is in SOURCE-video time:
 *  - subtitle track: one block per line; drag a block's edge to move the scene boundary (snaps to scene cuts)
 *  - voice track: how long the voice runs; red = longer than its slot (will be sped up / slow the video)
 *  - tap a block to edit its text, voice speed or delete it; "Split" adds a line at the playhead
 * Edits are applied with one re-render; only changed lines are re-voiced.
 */
export default function Editor({ project, videoRef, busy, onApply, finish = null, onFinish = () => {}, hasBackground = false, voices = [], looks = [], playingVoice = null, onPlaySample = () => {}, onPreviewLine = null, previewing = null }) {
  const { tr } = useI18n();
  const duration = project.source_duration;
  const model = project.voice_model || DEFAULT_MODEL;
  const predict = (text) => model.a * syllables(text) + model.b;
  const cuts = project.cuts || [];
  const initial = useMemo(
    () => project.segments.map((s) => ({ key: String(s.id), id: s.id, speaker: s.speaker || null, start: s.start, text: s.text, source_text: s.source_text || '', tempo: s.tempo ?? null })),
    [project]
  );
  const meta = useMemo(() => Object.fromEntries(project.segments.map((s) => [String(s.id), s])), [project]);
  const [lines, setLines] = useState(initial);
  const [selected, setSelected] = useState(initial[0]?.key ?? null);
  const [pps, setPps] = useState(48); // pixels per second (zoom)
  const [srcT, setSrcT] = useState(0); // playhead, source time
  const [playing, setPlaying] = useState(false);
  const scroller = useRef(null);
  const nextKey = useRef(1);
  const speakerIds = Object.keys(project.speakers || {});
  const subsOnly = project.output === 'subtitles';
  const colorOf = (sid) => (sid && speakerIds.includes(sid) ? PALETTE[speakerIds.indexOf(sid) % PALETTE.length] : PALETTE[0]);
  const [speakerVoices, setSpeakerVoices] = useState(() => Object.fromEntries(speakerIds.map((s) => [s, project.speakers[s].voice])));
  const [movedTo, setMovedTo] = useState({}); // character -> character its lines were moved to (shown in the 'move all lines' select)
  const liveCount = (sid) => lines.filter((l) => l.speaker === sid).length;
  const voicesChanged = speakerIds.some((s) => speakerVoices[s] !== project.speakers[s].voice);
  const initialFinish = useRef(finish);   // settings the video was made with (the editor is re-created for each new result)
  const finishChanged = !!finish && JSON.stringify(finish) !== JSON.stringify(initialFinish.current);
  const dirty = JSON.stringify(lines) !== JSON.stringify(initial) || voicesChanged || finishChanged;

  // ----- output time (what the video element plays) <-> source time (what the timeline shows) -----
  const timed = useMemo(() => project.segments.filter((s) => s.out_start != null).sort((a, b) => a.out_start - b.out_start), [project]);
  const outToSrc = useCallback((t) => {
    if (!timed.length) return t;
    if (t < timed[0].out_start) return timed[0].out_start ? (t / timed[0].out_start) * timed[0].start : 0;
    for (const s of timed) {
      if (t < s.out_start + s.out_len) return s.start + ((t - s.out_start) / s.out_len) * s.slot;
    }
    return duration;
  }, [timed, duration]);
  const srcToOut = useCallback((t) => {
    if (!timed.length) return t;
    if (t < timed[0].start) return timed[0].start ? (t / timed[0].start) * timed[0].out_start : 0;
    for (const s of timed) {
      if (t < s.start + s.slot) return s.out_start + ((t - s.start) / s.slot) * s.out_len;
    }
    const last = timed[timed.length - 1];
    return last.out_start + last.out_len;
  }, [timed]);

  // ----- playhead follows the video -----
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return undefined;
    let raf;
    const tick = () => {
      setSrcT(outToSrc(v.currentTime));
      raf = requestAnimationFrame(tick);
    };
    const onPlay = () => { setPlaying(true); raf = requestAnimationFrame(tick); };
    const onPause = () => { setPlaying(false); cancelAnimationFrame(raf); setSrcT(outToSrc(v.currentTime)); };
    const onSeek = () => setSrcT(outToSrc(v.currentTime));
    v.addEventListener('play', onPlay);
    v.addEventListener('pause', onPause);
    v.addEventListener('seeked', onSeek);
    if (!v.paused) onPlay();
    return () => { cancelAnimationFrame(raf); v.removeEventListener('play', onPlay); v.removeEventListener('pause', onPause); v.removeEventListener('seeked', onSeek); };
  }, [videoRef, outToSrc]);

  // keep the playhead in view while playing
  useEffect(() => {
    const el = scroller.current;
    if (!el || !playing) return;
    const x = srcT * pps;
    if (x < el.scrollLeft + 20 || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - el.clientWidth / 3;
  }, [srcT, playing, pps]);

  const seekSrc = (t) => {
    const v = videoRef.current;
    const c = clamp(t, 0, duration);
    setSrcT(c);
    if (v) v.currentTime = srcToOut(c);
  };
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) v.play(); else v.pause();
  };
  const timeFromEvent = (e) => {
    const rect = scroller.current.getBoundingClientRect();
    return (e.clientX - rect.left + scroller.current.scrollLeft) / pps;
  };

  // ----- lines -----
  const patch = (key, change) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const index = lines.findIndex((l) => l.key === selected);
  const sel = lines[index];
  const slotOf = (i) => Math.max((i + 1 < lines.length ? lines[i + 1].start : duration) - lines[i].start, MIN_LEN);

  const split = () => {
    const t = Math.round(srcT * 10) / 10;
    if (lines.some((l) => Math.abs(l.start - t) < MIN_LEN) || t <= 0 || t >= duration - MIN_LEN) return;
    const key = `new${nextKey.current++}`;
    setLines((ls) => [...ls, { key, start: t, text: '', source_text: '', tempo: null }].sort((a, b) => a.start - b.start));
    setSelected(key);
  };
  const remove = () => {
    if (!sel) return;
    setLines((ls) => ls.filter((l) => l.key !== sel.key));
    setSelected(lines[index + 1]?.key ?? lines[index - 1]?.key ?? null);
  };

  // drag a boundary: moves the START of line `i` (its left edge = previous line's right edge); snaps to scene cuts
  const drag = useRef(null);
  const beginDrag = (e, i) => {
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { i, x: e.clientX, v: lines[i].start };
  };
  const moveDrag = (e) => {
    const d = drag.current;
    if (!d) return;
    const lo = d.i > 0 ? lines[d.i - 1].start + MIN_LEN : 0;
    const hi = (d.i + 1 < lines.length ? lines[d.i + 1].start : duration) - MIN_LEN;
    let v = d.v + (e.clientX - d.x) / pps;
    const near = cuts.find((c) => Math.abs(c - v) * pps < 8); // magnet to a scene cut
    if (near !== undefined) v = near;
    patch(lines[d.i].key, { start: Math.round(clamp(v, lo, Math.max(lo, hi)) * 100) / 100 });
  };
  const endDrag = () => { drag.current = null; };

  const voiceLen = (l, i) => {
    const m = meta[l.key];
    const same = m && m.text === l.text;
    const dur = same ? m.audio_dur : predict(l.text); // unchanged line: real length; edited line: predicted, no TTS call
    return dur / (l.tempo ?? (same && m.applied_tempo) ?? 1);
  };

  const width = duration * pps;
  const step = pps >= 90 ? 1 : pps >= 40 ? 2 : pps >= 20 ? 5 : 10;
  const ticks = Array.from({ length: Math.floor(duration / step) + 1 }, (_, n) => n * step);
  const activeKey = lines.filter((l) => l.start <= srcT).pop()?.key;
  const selSlot = sel ? slotOf(index) : 0;
  const selVoice = sel ? voiceLen(sel, index) : 0;
  const fitRatio = selVoice / Math.max(selSlot - 0.1, 0.2);
  const tone = fitRatio > 1.35 ? 'text-red-400' : fitRatio > 1.02 ? 'text-amber-400' : fitRatio < 0.8 ? 'text-sky-400' : 'text-emerald-400';
  const fitNote = fitRatio > 1.35 ? tr('too long: voice rushes or the video slows')
    : fitRatio > 1.02 ? tr('slightly long: small speed-up')
    : fitRatio < 0.8 ? tr('{s}s of silence: add words or shorten the scene', { s: (selSlot - 0.1 - selVoice).toFixed(1) })
    : tr('fits the scene');
  const total = lines.reduce((sum, l, i) => sum + Math.max(slotOf(i), voiceLen(l, i) + 0.1), 0);

  return (
    <fieldset
      disabled={busy}
      className={`w-full mt-6 border-0 border-t border-slate-800 pt-4 select-none min-w-0 transition-opacity ${busy ? 'opacity-40 pointer-events-none' : ''}`}
    >
      {/* toolbar */}
      <div className="flex items-center gap-2 mb-2 text-sm">
        <button type="button" onClick={togglePlay} className="w-9 h-9 rounded-full bg-white text-slate-900 font-bold">{playing ? '❚❚' : '▶'}</button>
        <span className="font-mono text-xs text-slate-300">{fmt(srcT)} / {fmt(duration)}</span>
        <span className="ml-auto flex items-center gap-1 text-xs text-slate-400">
          −<input type="range" min="12" max="160" value={pps} onChange={(e) => setPps(Number(e.target.value))} className="w-24 accent-purple-500" />+
        </span>
      </div>

      {/* timeline */}
      <div className="rounded-xl bg-slate-900 border border-slate-800 overflow-hidden">
        <div ref={scroller} className="overflow-x-auto relative" style={{ touchAction: 'pan-x' }}>
          <div className="relative" style={{ width, minWidth: '100%' }} onClick={(e) => seekSrc(timeFromEvent(e))}>
            {/* ruler + scene cuts */}
            <div className="h-6 relative border-b border-slate-800 cursor-pointer">
              {ticks.map((t) => (
                <div key={t} className="absolute top-0 text-[10px] text-slate-500 pl-1 border-l border-slate-700 h-full" style={{ left: t * pps }}>{t}s</div>
              ))}
              {cuts.map((c) => (
                <div key={c} className="absolute bottom-0 w-px h-2 bg-cyan-400/70" style={{ left: c * pps }} />
              ))}
            </div>
            {/* subtitle track */}
            <div className="relative h-12 mt-1">
              {lines.map((l, i) => {
                const slot = slotOf(i);
                const on = l.key === selected;
                return (
                  <div
                    key={l.key}
                    onClick={(e) => { e.stopPropagation(); setSelected(l.key); seekSrc(timeFromEvent(e)); }}
                    className={`absolute top-0 h-12 rounded-lg overflow-hidden px-2 text-xs leading-tight pt-1 cursor-pointer border-2 text-white ${
                      on ? 'border-white' : l.key === activeKey ? 'border-white/60' : 'border-transparent'
                    }`}
                    style={{ left: l.start * pps + 1, width: Math.max(slot * pps - 2, 6), backgroundColor: colorOf(l.speaker), opacity: on || l.key === activeKey ? 1 : 0.8 }}
                    title={l.text}
                  >
                    <span className="line-clamp-2 break-words">{l.text || tr('(empty line: type text below)')}</span>
                    {/* left handle = this line's start */}
                    <div
                      onPointerDown={(e) => beginDrag(e, i)} onPointerMove={moveDrag} onPointerUp={endDrag} onClick={(e) => e.stopPropagation()}
                      className={`absolute left-0 top-0 h-full w-3 cursor-ew-resize ${on ? 'bg-white/90' : 'bg-white/20'}`} style={{ touchAction: 'none' }}
                    />
                  </div>
                );
              })}
            </div>
            {/* voice track */}
            {!subsOnly && <div className="relative h-6 mt-1 mb-2">
              {lines.map((l, i) => {
                const len = voiceLen(l, i);
                const over = len > slotOf(i) * 1.02;
                return (
                  <div
                    key={l.key}
                    className={`absolute top-0 h-6 rounded-md text-[10px] px-1 flex items-center ${over ? 'bg-red-500/70 text-white' : 'bg-emerald-600/70 text-white'}`}
                    style={{ left: l.start * pps + 1, width: Math.max(len * pps - 2, 4), opacity: l.key === selected ? 1 : 0.7 }}
                    title={over ? tr('Voice is longer than its scene: it will speed up or the video will slow down') : tr('Voice fits its scene')}
                  >
                    ♪ {len.toFixed(1)}s
                  </div>
                );
              })}
            </div>}
            {/* playhead */}
            <div className="absolute top-0 bottom-0 w-0.5 bg-white pointer-events-none" style={{ left: srcT * pps }}>
              <div className="w-2.5 h-2.5 rounded-full bg-white -ml-1" />
            </div>
          </div>
        </div>
        <div className="flex gap-4 px-3 py-1.5 text-[10px] text-slate-500 border-t border-slate-800">
          <span><i className="inline-block w-2 h-2 bg-purple-600 rounded-sm mr-1" />{tr('subtitle (drag the left edge to move a scene boundary)')}</span>
          <span><i className="inline-block w-2 h-2 bg-red-500 rounded-sm mr-1" />{tr('voice too long')}</span>
          <span><i className="inline-block w-2 h-0.5 bg-cyan-400 mr-1" />{tr('scene cut')}</span>
        </div>
      </div>

      {/* characters (full movie mode): one fixed voice each */}
      {speakerIds.length > 0 && !subsOnly && (
        <div className="mt-3 rounded-xl bg-slate-800/60 border border-slate-700 p-3">
          <p className="text-xs text-slate-400 mb-2">{tr("Characters: each keeps one voice for the whole film. Change a voice, then re-render (only that character's lines are re-voiced).")}</p>
          <div className="flex flex-wrap gap-3">
            {speakerIds.map((sid) => (
              <label key={sid} className={`flex flex-wrap items-center gap-2 text-xs text-slate-300 ${liveCount(sid) === 0 ? 'opacity-50' : ''}`}>
                <span className="px-1.5 py-0.5 rounded text-white font-semibold" style={{ backgroundColor: colorOf(sid) }}>{sid}</span>
                <span className="text-slate-500">{project.speakers[sid].gender !== 'unknown' ? tr(project.speakers[sid].gender) : ''} · {tr('{n} lines', { n: liveCount(sid) })}</span>
                <select
                  value={speakerVoices[sid]} onChange={(ev) => setSpeakerVoices({ ...speakerVoices, [sid]: ev.target.value })}
                  className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-xs"
                >
                  {voices.length === 0 && <option value={speakerVoices[sid]}>{speakerVoices[sid]}</option>}
                  <optgroup label={tr('Voices')}>
                    {voices.map((v) => <option key={v.name} value={v.name}>{v.name} ({tr(v.gender)})</option>)}
                  </optgroup>
                  {looks.length > 0 && (
                    <optgroup label={tr('Character looks')}>
                      {looks.map((l) => <option key={l.id} value={`look:${l.id}`}>{tr(l.label)} · {l.voice}</option>)}
                    </optgroup>
                  )}
                </select>
                {(() => {
                  const lk = looks.find((x) => `look:${x.id}` === speakerVoices[sid]);
                  const vv = lk ? { name: `look:${lk.id}`, sample_url: lk.sample_url } : voices.find((x) => x.name === speakerVoices[sid]);
                  return vv ? (
                    <button type="button" onClick={() => onPlaySample(vv)} title={tr('Play a sample of this voice')}
                      className="w-7 h-7 rounded-full bg-slate-700 hover:bg-slate-600 text-white text-xs flex items-center justify-center">
                      {playingVoice === vv.name ? '■' : '🔊'}
                    </button>
                  ) : null;
                })()}
                {speakerIds.length > 1 && (
                  <select
                    value={liveCount(sid) === 0 ? (movedTo[sid] || '') : ''} title={tr('Same person as another character? Give all these lines to that character.')}
                    onChange={(ev) => {
                      const to = ev.target.value;
                      if (!to) return;
                      setLines(lines.map((l) => (l.speaker === sid ? { ...l, speaker: to } : l)));
                      setMovedTo({ ...movedTo, [sid]: to });
                    }}
                    className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-xs text-slate-400"
                  >
                    <option value="">{tr('move all lines to…')}</option>
                    {speakerIds.filter((o) => o !== sid && (lines.some((l) => l.speaker === o) || movedTo[sid] === o)).map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                )}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* selected line */}
      <div className="mt-3 rounded-xl bg-slate-800/60 border border-slate-700 p-3">
        {sel ? (
          <>
            <div className="flex items-center gap-2 text-xs mb-2">
              <span className="text-slate-400">{tr('Line {n} · {time} · slot {s}s', { n: index + 1, time: fmt(sel.start), s: selSlot.toFixed(1) })}</span>
              {speakerIds.length > 0 && (
                <span className="flex items-center gap-1" title={tr('Which character says this line')}>
                  {speakerIds.map((sid) => (
                    <button key={sid} type="button" onClick={() => patch(sel.key, { speaker: sid })}
                      title={`${sid}: ${speakerVoices[sid]}`}
                      className={`w-6 h-6 rounded-md text-[11px] font-semibold text-white ${sel.speaker === sid ? 'ring-2 ring-white' : 'opacity-50 hover:opacity-100'}`}
                      style={{ backgroundColor: colorOf(sid) }}>{sid}</button>
                  ))}
                </span>
              )}
              {!subsOnly && onPreviewLine && speakerVoices[sel.speaker] && (
                <button type="button" disabled={previewing != null} title={tr('Hear this line in the chosen character\'s voice (1 voice request, kept for Apply)')}
                  onClick={() => onPreviewLine(sel, speakerVoices[sel.speaker])}
                  className="px-2 py-0.5 rounded-full bg-purple-600 text-white disabled:opacity-50">
                  {previewing === sel.key ? '…' : `▶ ${tr('Hear')} ${looks.find((x) => `look:${x.id}` === speakerVoices[sel.speaker])?.label ?? speakerVoices[sel.speaker]}`}
                </button>
              )}
              {meta[sel.key]?.emotion && meta[sel.key].emotion !== 'neutral' && <span className="text-amber-300">{tr(meta[sel.key].emotion)}</span>}
              {!subsOnly && <span className={`ml-auto ${tone}`} title={tr('Predicted from the text, no voice request needed')}>{tr('≈ {s}s voice · {note}', { s: selVoice.toFixed(1), note: fitNote })}</span>}
              <button type="button" onClick={() => patch(sel.key, { start: Math.round(clamp(sel.start - 0.1, index > 0 ? lines[index - 1].start + MIN_LEN : 0, duration) * 100) / 100 })} className="px-2 py-0.5 rounded bg-slate-700">−0.1s</button>
              <button type="button" onClick={() => patch(sel.key, { start: Math.round(clamp(sel.start + 0.1, 0, (index + 1 < lines.length ? lines[index + 1].start : duration) - MIN_LEN) * 100) / 100 })} className="px-2 py-0.5 rounded bg-slate-700">+0.1s</button>
            </div>
            <textarea
              rows={3} value={sel.text} onChange={(e) => patch(sel.key, { text: e.target.value })} placeholder={tr('Burmese text for this line')}
              className="w-full rounded-lg bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-white outline-none focus:border-purple-500"
            />
            {sel.source_text && <p className="text-[11px] text-slate-500 mt-1">{tr('Original: {text}', { text: sel.source_text })}</p>}
            <div className="flex flex-wrap items-center gap-1.5 mt-2 text-xs">
              {!subsOnly && <span className="text-slate-400 mr-1">{tr('Voice speed')}</span>}
              {!subsOnly && TEMPOS.map((t) => (
                <button
                  key={t ?? 'auto'} type="button" onClick={() => patch(sel.key, { tempo: t })}
                  className={`px-2 py-1 rounded-full ${sel.tempo === t ? 'bg-purple-600 text-white' : 'bg-slate-700 text-slate-300'}`}
                >{t == null ? tr('Auto') : `${t.toFixed(1)}x`}</button>
              ))}
              <button type="button" onClick={remove} className="ml-auto px-3 py-1 rounded-full bg-red-900/60 text-red-200 hover:bg-red-800">{tr('Delete line')}</button>
            </div>
          </>
        ) : (
          <p className="text-xs text-slate-400">{tr('Tap a subtitle block on the timeline to edit it, or press Split to add a line at the playhead.')}</p>
        )}
      </div>

      {finish && (
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3 mt-3 space-y-2 text-sm text-slate-300">
          <p className="text-xs font-semibold text-slate-200">{tr('Look & sound (applied when you re-render)')}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {[
              ['blur_subtitles', tr('Blur original subtitles')],
              ['enable_subtitles', tr('Burmese subtitles')],
              ['remove_watermark', tr('Blur lower-right watermark')],
              ['enable_flip', tr('Horizontal flip')],
            ].map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={!!finish[key]} onChange={(e) => onFinish({ [key]: e.target.checked })} className="w-4 h-4 accent-purple-500" />
                {label}
              </label>
            ))}
          </div>
          {hasBackground && !subsOnly && (
            <label className="block text-xs text-slate-400">
              {tr('Original music & effects volume')}: <span className="text-slate-200">{Math.round((finish.bg_volume ?? 0.8) * 100)}%</span>
              <input type="range" min={0} max={1.5} step={0.05} value={finish.bg_volume ?? 0.8}
                onChange={(e) => onFinish({ bg_volume: Number(e.target.value) })} className="w-full accent-purple-500" />
            </label>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2 mt-3">
        <button type="button" onClick={split} className="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-sm">{tr('✂ Split / add line at playhead')}</button>
        <button type="button" disabled={!dirty || busy || lines.every((l) => !l.text.trim())}
          onClick={() => onApply([...lines].sort((a, b) => a.start - b.start).map((l) => ({ id: l.id ?? null, speaker: l.speaker, start: Number(l.start), text: l.text, source_text: l.source_text, tempo: l.tempo })), voicesChanged ? speakerVoices : undefined)}
          className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 font-semibold text-sm disabled:opacity-40">
          {busy ? tr('Re-rendering…') : tr('Apply changes & re-render')}
        </button>
        {dirty && !busy && (
          <button type="button" onClick={() => { setLines(initial); setSelected(initial[0]?.key ?? null); setSpeakerVoices(Object.fromEntries(speakerIds.map((s) => [s, project.speakers[s].voice]))); setMovedTo({}); if (finish) onFinish(initialFinish.current); }} className="px-3 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-sm">{tr('Reset')}</button>
        )}
        {dirty && !busy && <span className="self-center text-xs text-amber-300">{tr('Not applied yet: press "Apply changes & re-render" to hear it.')}</span>}
        <span className="self-center text-xs text-slate-500">{tr('Only changed lines are re-voiced. Estimated length ≈ {t}.', { t: fmt(total) })}</span>
      </div>
    </fieldset>
  );
}
