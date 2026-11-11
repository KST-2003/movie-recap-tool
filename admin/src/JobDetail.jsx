import React, { useState } from 'react';
import { Copy } from 'lucide-react';
import { useI18n } from './i18n.jsx';
import { fmtTime, Badge, Sheet, useApi, ErrorBox, btnGhost } from './ui.jsx';

// One video in detail: the full error, where it stopped, and EVERY option the user chose, so a failure can be traced to the settings behind it.
const GROUPS = [
  ['Upload', ['filename', 'mode', 'output', 'aspect', 'fit_mode', 'pan_x', 'pan_y', 'target_language']],
  ['Voice', ['voice_quality', 'voice_type', 'emotion', 'background', 'keep_background', 'soft_music']],
  ['Look', ['blur_subtitles', 'enable_subtitles', 'remove_watermark', 'enable_flip', 'flip_vertical', 'video_speed', 'brightness', 'contrast', 'saturation',
    'logo_position', 'logo_size', 'logo_x', 'logo_y', 'manual_blurs']],
  ['Timing', ['fit_translation', 'allow_voice_speedup', 'max_voice_speedup', 'min_video_speed']],
  ['Server', ['reserved_model', 'reserved_requests']],
];
const LABELS = {
  filename: 'File name', mode: 'Mode', output: 'Output', aspect: 'Format', fit_mode: 'Fit / crop', pan_x: 'Pan x', pan_y: 'Pan y', target_language: 'Language',
  voice_quality: 'Voice quality', voice_type: 'Voice', emotion: 'Emotion directions', background: 'Original sound', keep_background: 'Keep original music', soft_music: 'Soft tone',
  blur_subtitles: 'Blur original subtitles', enable_subtitles: 'Burmese subtitles', remove_watermark: 'Blur watermark', enable_flip: 'Flip horizontally', flip_vertical: 'Flip vertically',
  video_speed: 'Video speed', brightness: 'Brightness', contrast: 'Contrast', saturation: 'Saturation', logo_position: 'Logo corner', logo_size: 'Logo size', logo_x: 'Logo x', logo_y: 'Logo y',
  manual_blurs: 'Manual blur boxes', fit_translation: 'Fit script to speech', allow_voice_speedup: 'Allow voice speed-up', max_voice_speedup: 'Max voice speed-up', min_video_speed: 'Min video speed',
  reserved_model: 'Reserved voice model', reserved_requests: 'Reserved voice requests',
};

export default function JobDetail({ id, onClose }) {
  const { tr, trs } = useI18n();
  const { data: d, error, reload } = useApi(`/api/admin/jobs/${id}`, { every: 8000 });
  const [copied, setCopied] = useState(false);

  const show = (v) => {
    if (v === null || v === undefined || v === '') return '–';
    if (typeof v === 'boolean') return v ? tr('Yes') : tr('No');
    if (Array.isArray(v)) return v.length ? `${v.length} ${tr('items')}: ${JSON.stringify(v).slice(0, 160)}` : '–';
    if (typeof v === 'object') return JSON.stringify(v).slice(0, 160);
    return String(v);
  };
  const t0 = d?.stages?.length ? new Date(d.stages[0].at).getTime() : 0;
  const rows = (keys) => keys.filter((k) => d.params && k in d.params);
  const used = d ? GROUPS.flatMap(([, k]) => k) : [];
  const other = d ? Object.keys(d.params || {}).filter((k) => !used.includes(k)) : [];

  const report = () => {
    const lines = [`Job ${d.id} (${d.status}) - ${d.user.email}`, `Created ${d.created_at}, finished ${d.finished_at || '-'}, run ${d.run_seconds ?? '-'} s`,
      `Stage: ${d.stage} (${d.progress}%)`, d.failed_stage ? `Failed at: ${d.failed_stage.stage} (${d.failed_stage.progress}%) ${d.failed_stage.at}` : '',
      d.error ? `Error: ${d.error}` : '', d.error_detail ? `Details:\n${d.error_detail}` : '', 'Options:', ...Object.entries(d.params || {}).map(([k, v]) => `  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`),
      'Stages:', ...d.stages.map((s) => `  ${s.at} ${s.progress}% ${s.stage}`),
      ...(d.log?.length ? ['Log:', ...d.log] : [])];
    return lines.filter((l) => l !== '').join('\n');
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(report()); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch (e) { /* clipboard blocked: the text can still be selected by hand */ }
  };
  const Section = ({ title, children }) => <section className="mt-5"><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h4>{children}</section>;
  const Rows = ({ list }) => (
    <dl className="divide-y divide-slate-800 rounded-xl border border-slate-800 text-sm">
      {list.map(([k, v]) => <div key={k} className="flex justify-between gap-4 px-3 py-2"><dt className="flex-shrink-0 text-slate-400">{k}</dt><dd className="break-all text-right">{v}</dd></div>)}
    </dl>
  );

  return (
    <Sheet wide title={tr('Video details')} onClose={onClose}>
      <ErrorBox error={error} onRetry={reload} />
      {!d ? (!error && <p className="py-6 text-center text-sm text-slate-500">{tr('Loading…')}</p>) : (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge status={d.status} />
            <span className="break-all text-sm">{d.user.email}</span>
            <span className="text-xs text-slate-500">· {d.id}</span>
            <button className={`${btnGhost} ml-auto !px-2.5 !py-1.5 text-xs`} onClick={copy}><Copy size={13} />{copied ? tr('Copied') : tr('Copy all details')}</button>
          </div>

          {d.status === 'error' && (
            <Section title={tr('Error')}>
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3">
                <pre className="whitespace-pre-wrap break-words font-mono text-xs text-red-200 select-text">{d.error || tr('No message was saved.')}</pre>
                {d.failed_stage && <p className="mt-2 text-xs text-red-300/80">{tr('It stopped at: {stage} ({p}%)', { stage: d.failed_stage.stage, p: d.failed_stage.progress })} · {fmtTime(d.failed_stage.at)}</p>}
              </div>
              {d.error_detail && (
                <details className="mt-2 rounded-xl border border-slate-800 p-3">
                  <summary className="cursor-pointer text-xs text-slate-400">{tr('Technical details (where in the code)')}</summary>
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-slate-300 select-text">{d.error_detail}</pre>
                </details>
              )}
            </Section>
          )}

          <Section title={tr('Summary')}>
            <Rows list={[
              [tr('Status'), `${tr(d.status)} · ${d.status === 'running' ? `${d.progress}% · ` : ''}${trs(d.stage)}`],
              [tr('Started'), fmtTime(d.created_at)], [tr('Finished'), fmtTime(d.finished_at)],
              [tr('Took'), d.run_seconds == null ? '–' : `${Math.round(d.run_seconds)} s`],
              [tr('Minutes charged'), `${d.charged_minutes} ${tr('allowance')} + ${d.bought_minutes} ${tr('bought')}`],
              [tr('Cost'), d.cost_thb == null ? '–' : `${d.cost_thb} THB${d.cost_complete ? '' : ' *'}`],
              [tr('Source video still kept'), show(d.source_kept)], [tr('Logo uploaded'), show(d.has_logo)],
            ]} />
          </Section>

          <Section title={tr('What the user chose')}>
            <div className="space-y-3">
              {GROUPS.map(([g, keys]) => rows(keys).length > 0 && (
                <div key={g}><p className="mb-1 text-[11px] text-slate-500">{tr(g)}</p><Rows list={rows(keys).map((k) => [tr(LABELS[k] || k), show(d.params[k])])} /></div>
              ))}
              {other.length > 0 && <div><p className="mb-1 text-[11px] text-slate-500">{tr('Other')}</p><Rows list={other.map((k) => [k, show(d.params[k])])} /></div>}
              <details className="rounded-xl border border-slate-800 p-3"><summary className="cursor-pointer text-xs text-slate-400">{tr('Raw options (JSON)')}</summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-slate-300 select-text">{JSON.stringify(d.params, null, 2)}</pre></details>
            </div>
          </Section>

          <Section title={tr('Steps')}>
            {d.stages.length === 0 ? <p className="text-xs text-slate-500">{tr('No step history was recorded for this video.')}</p> : (
              <ol className="divide-y divide-slate-800 rounded-xl border border-slate-800 text-sm">
                {d.stages.map((s, i) => (
                  <li key={i} className="flex items-center justify-between gap-3 px-3 py-1.5">
                    <span className="min-w-0 break-words">{trs(s.stage)}</span>
                    <span className="flex-shrink-0 text-xs text-slate-500">{s.progress}% · +{Math.max(0, Math.round((new Date(s.at).getTime() - t0) / 1000))} s</span>
                  </li>
                ))}
              </ol>
            )}
          </Section>

          <Section title={tr('Log (what the server printed for this video)')}>
            {!d.log?.length ? <p className="text-xs text-slate-500">{tr('No log was recorded for this video (videos made before this feature have none).')}</p> : (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-300 select-text">{d.log.join('\n')}</pre>
            )}
            {d.status === 'running' && <p className="mt-1 text-xs text-slate-500">{tr('Updates about every 8 seconds while the video is running.')}</p>}
          </Section>

          {d.result?.warnings?.length > 0 && (
            <Section title={tr('Warnings')}><ul className="list-disc space-y-1 pl-5 text-xs text-amber-200">{d.result.warnings.map((w, i) => <li key={i}>{trs(w)}</li>)}</ul></Section>
          )}
        </div>
      )}
    </Sheet>
  );
}
