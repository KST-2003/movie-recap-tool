import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useI18n } from './i18n.jsx';
import Select from './Select.jsx';
import PreviewStudio, { ASPECTS } from './PreviewStudio.jsx';
import CaptionStyleControls from './CaptionStyleControls.jsx';
import { DEFAULT_CAPTION_STYLE } from './captionFonts.js';
import { voiceLabel } from './voiceNames.js';

// Preset builder: the settings of a NEW video, with a live preview (sample video, or the user's own file, never uploaded).
// Used by the user app (Presets page) and, copied by admin/scripts/sync-preset.mjs, by the admin app (presets for everybody).
// A preset stores a whitelist of form fields (backend presets.py RULES); the logo file and hand-drawn blur boxes are per video and not stored.

export const PRESET_DEFAULTS = {
  aspect: 'original', fitMode: 'blur', resolution: '720', videoSpeed: 1, brightness: 0, contrast: 1, saturation: 1,
  blurSubtitles: true, watermark: false, flip: false, voiceQuality: 'standard', voiceType: 'Kore', filmMode: 'recap', outputKind: 'dub',
  bgMode: 'separate', emotionOn: true, softMusic: false, captionStyle: { ...DEFAULT_CAPTION_STYLE },
};

const card = 'rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-3';
const chip = (on) => `px-3 py-2 rounded-2xl text-sm border ${on ? 'border-violet-400 bg-violet-500 text-white' : 'border-violet-200 bg-white text-ink-soft'}`;

export default function PresetEditor({ apiBase = '', initial, admin = false, saving = false, error = '', onSave, onCancel }) {
  const { tr, lang } = useI18n();
  const [name, setName] = useState(initial?.name || '');
  const [status, setStatus] = useState(initial?.status || 'draft');
  const [set, setSet] = useState({ ...PRESET_DEFAULTS, ...(initial?.settings || {}), captionStyle: { ...DEFAULT_CAPTION_STYLE, ...(initial?.settings?.captionStyle || {}) } });
  const [voices, setVoices] = useState([]);
  const [standardOk, setStandardOk] = useState(true);
  const [separationOk, setSeparationOk] = useState(true);
  const [ownFile, setOwnFile] = useState(null);
  const [ownUrl, setOwnUrl] = useState('');
  const up = (patch) => setSet((s) => ({ ...s, ...patch }));

  useEffect(() => {
    axios.get(`${apiBase}/api/voices`).then((r) => setVoices(r.data)).catch(() => setVoices([]));
    axios.get(`${apiBase}/api/voice-quality`).then((r) => { setStandardOk(!!r.data.standard); setSeparationOk(r.data.separation !== false); }).catch(() => {});
  }, [apiBase]);
  useEffect(() => {
    if (!ownFile) { setOwnUrl(''); return undefined; }
    const u = URL.createObjectURL(ownFile);
    setOwnUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [ownFile]);

  const standard = set.voiceQuality === 'standard' && standardOk;
  const subtitlesOn = set.outputKind !== 'voice';
  const fx = { videoSpeed: set.videoSpeed, brightness: set.brightness, contrast: set.contrast, saturation: set.saturation, logoSize: 0.15, logoPosition: 'top-right', logoXY: null,
    blurBoxes: [], logoOnTop: false, flip: set.flip, aspect: set.aspect, fitMode: set.fitMode, panX: 0.5, panY: 0.5, captionStyle: subtitlesOn ? set.captionStyle : null };
  const changeFx = (patch) => {
    const map = { videoSpeed: 'videoSpeed', brightness: 'brightness', contrast: 'contrast', saturation: 'saturation', captionStyle: 'captionStyle' };
    const out = {};
    Object.entries(patch).forEach(([k, v]) => { if (map[k]) out[map[k]] = v; });
    if (Object.keys(out).length) up(out);
  };
  const sample = `${import.meta.env.BASE_URL}preset-sample.mp4`;

  const submit = (e) => {
    e.preventDefault();
    const { captionStyle, ...rest } = set;
    const settings = { ...rest, voiceQuality: standard ? 'standard' : 'premium', captionStyle };
    onSave(name.trim(), settings, status);
  };

  const femaleVoices = voices.filter((v) => v.gender === 'female');
  const maleVoices = voices.filter((v) => v.gender === 'male');
  return (
    <form onSubmit={submit} className="space-y-5">
      <div className={card}>
        <label className="block text-sm font-medium text-ink-soft" htmlFor="preset-name">{tr('Preset name')}</label>
        <input id="preset-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={40} required placeholder={tr('e.g. TikTok vertical')}
          className="w-full rounded-2xl border border-violet-200 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-violet-400" />
        {admin && (
          <div>
            <p className="text-sm font-medium text-ink-soft mb-1">{tr('Status')}</p>
            <div className="flex gap-2">
              {[['draft', tr('Draft (only admins see it)')], ['published', tr('Submitted (all users can use it)')]].map(([k, label]) => (
                <button key={k} type="button" onClick={() => setStatus(k)} aria-pressed={status === k} className={chip(status === k)}>{label}</button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className={card}>
        <p className="text-sm font-semibold text-ink">{tr('Video format')}</p>
        <div className="flex flex-wrap gap-2">
          {[['original', tr('Original')], ['9:16', '9:16'], ['1:1', '1:1'], ['4:5', '4:5'], ['16:9', '16:9']].map(([k, label]) => {
            const [w, h] = ASPECTS[k] || [3, 4];
            const s = 22 / Math.max(w, h);
            return (
              <button key={k} type="button" onClick={() => up({ aspect: k })} aria-pressed={set.aspect === k}
                className={`flex items-center gap-2 ${chip(set.aspect === k)}`}>
                <span className="inline-block border-2 rounded-sm border-current" style={{ width: ASPECTS[k] ? w * s : 18, height: ASPECTS[k] ? h * s : 18, borderStyle: ASPECTS[k] ? 'solid' : 'dashed' }} />
                {label}
              </button>
            );
          })}
        </div>
        {set.aspect !== 'original' && (
          <div className="flex gap-4 text-sm text-ink-soft flex-wrap">
            {[['blur', tr('Fit (blurred background)')], ['crop', tr('Fill (crop)')]].map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="preset-fit" checked={set.fitMode === k} onChange={() => up({ fitMode: k })} className="accent-violet-500" />
                {label}
              </label>
            ))}
          </div>
        )}
      </div>

      <div className={card}>
        <p className="text-sm font-semibold text-ink">{tr('Preview')}</p>
        <p className="text-xs text-ink-faint">{tr('This is how videos made with this preset will look. A sample clip is shown; you can try your own video here (it is not uploaded).')}</p>
        <PreviewStudio src={ownUrl || sample} logoFile={null} fx={fx} onChange={changeFx} simple />
        <div className="flex items-center gap-2 text-xs text-ink-soft">
          <input type="file" accept="video/*" onChange={(e) => setOwnFile(e.target.files[0] || null)}
            className="min-w-0 flex-1 text-xs text-ink-soft file:mr-3 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-violet-100 file:text-ink cursor-pointer" />
          {ownFile && <button type="button" onClick={() => setOwnFile(null)} className="underline">{tr('Use the sample')}</button>}
        </div>
      </div>

      <div className={card}>
        <p className="text-sm font-semibold text-ink">{tr('Finishing options')}</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-ink-soft">
          {[['blurSubtitles', tr('Blur original subtitles'), set.blurSubtitles, (v) => up({ blurSubtitles: v })],
            ['subtitles', tr('Burmese subtitles'), subtitlesOn, (v) => up({ outputKind: v ? (set.outputKind === 'voice' ? 'dub' : set.outputKind) : 'voice' })],
            ['watermark', tr('Blur lower-right watermark'), set.watermark, (v) => up({ watermark: v })],
            ['flip', tr('Horizontal flip'), set.flip, (v) => up({ flip: v })]].map(([key, label, on, change]) => (
            <label key={key} className={`flex items-center gap-2 ${key === 'subtitles' && set.outputKind === 'subtitles' ? 'opacity-60' : 'cursor-pointer'}`}>
              <input type="checkbox" disabled={key === 'subtitles' && set.outputKind === 'subtitles'} checked={key === 'subtitles' && set.outputKind === 'subtitles' ? true : !!on}
                onChange={(e) => change(e.target.checked)} className="w-4 h-4 accent-violet-500" />
              {label}
            </label>
          ))}
        </div>
        {subtitlesOn && <CaptionStyleControls cap={set.captionStyle} onChange={(c) => up({ captionStyle: c })} showSample={false} />}
      </div>

      <div className={card}>
        <p className="text-sm font-semibold text-ink">{tr('Voice and output')}</p>
        {standardOk && (
          <div className="flex flex-wrap gap-2">
            {[['standard', tr('Standard voice')], ['premium', tr('High quality voice')]].map(([q, label]) => (
              <button key={q} type="button" aria-pressed={set.voiceQuality === q} onClick={() => up({ voiceQuality: q, ...(q === 'standard' ? { voiceType: set.voiceType === 'Charon' ? 'Charon' : 'Kore', emotionOn: false } : {}) })} className={chip(set.voiceQuality === q)}>{label}</button>
            ))}
          </div>
        )}
        {set.outputKind !== 'subtitles' && (standard ? (
          <div className="flex gap-2">
            {[['Kore', 'Nilar', tr('female')], ['Charon', 'Thiha', tr('male')]].map(([v, label, g]) => (
              <button key={v} type="button" onClick={() => up({ voiceType: v })} aria-pressed={set.voiceType === v} className={chip(set.voiceType === v)}>{label} · {g}</button>
            ))}
          </div>
        ) : (
          <label className="block text-xs text-ink-soft">{tr('Voice')}
            <Select size="sm" className="mt-1 w-full" value={set.voiceType} onChange={(v) => up({ voiceType: v })}
              options={[...femaleVoices.map((v) => ({ value: v.name, label: `${voiceLabel(v.name, lang)} (${tr('female')})`, group: tr('Female voices') })),
                        ...maleVoices.map((v) => ({ value: v.name, label: `${voiceLabel(v.name, lang)} (${tr('male')})`, group: tr('Male voices') }))]} />
          </label>
        ))}
        <div>
          <p className="text-xs text-ink-soft mb-1">{tr('Video type')}</p>
          <div className="flex gap-2">
            {[['recap', tr('Recap video')], ['full', tr('Full movie / drama')]].map(([k, label]) => (
              <button key={k} type="button" onClick={() => up({ filmMode: k })} aria-pressed={set.filmMode === k} className={chip(set.filmMode === k)}>{label}</button>
            ))}
          </div>
        </div>
        <div>
          <p className="text-xs text-ink-soft mb-1">{tr('Output')}</p>
          <div className="flex flex-wrap gap-2">
            {[['dub', tr('Burmese voice-over + subtitles')], ['voice', tr('Burmese voice-over only (no subtitles)')], ['subtitles', tr('Subtitles only, original sound stays')]].map(([k, label]) => (
              <button key={k} type="button" onClick={() => up({ outputKind: k })} aria-pressed={set.outputKind === k} className={chip(set.outputKind === k)}>{label}</button>
            ))}
          </div>
        </div>
        {set.filmMode === 'full' && set.outputKind !== 'subtitles' && (
          <label className="block text-xs text-ink-soft">{tr('Original sound')}
            <Select size="sm" className="mt-1 w-full" value={set.bgMode} onChange={(v) => up({ bgMode: v })}
              options={[...(separationOk ? [{ value: 'separate', label: tr('Keep music & sound effects, remove the original speech') }] : []),
                        { value: 'original', label: tr('Keep everything, original sound quiet under the Burmese voice') }, { value: 'off', label: tr('No original sound') }]} />
          </label>
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm text-ink-soft">
          {!standard && set.outputKind !== 'subtitles' && <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={!!set.emotionOn} onChange={(e) => up({ emotionOn: e.target.checked })} className="w-4 h-4 accent-violet-500" />{tr('Emotion in the voice')}</label>}
          <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={!!set.softMusic} onChange={(e) => up({ softMusic: e.target.checked })} className="w-4 h-4 accent-violet-500" />{tr('Soft background tone')}</label>
        </div>
        <div>
          <p className="text-xs text-ink-soft mb-1">{tr('Video quality (size)')}</p>
          <div className="flex gap-2">
            {[['720', '720p'], ['1080', '1080p']].map(([k, label]) => (
              <button key={k} type="button" onClick={() => up({ resolution: k })} aria-pressed={set.resolution === k} className={chip(set.resolution === k)}>{label}</button>
            ))}
          </div>
        </div>
      </div>

      {error && <p role="alert" className="rounded-2xl bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={onCancel} className="flex-1 rounded-2xl border border-violet-200 bg-white py-3 text-sm font-semibold text-ink-soft">{tr('Cancel')}</button>
        <button type="submit" disabled={saving || !name.trim()} className="flex-[2] rounded-2xl bg-violet-500 py-3 text-sm font-semibold text-white shadow-pop disabled:opacity-50">{saving ? tr('Saving…') : tr('Save preset')}</button>
      </div>
    </form>
  );
}
