import React, { lazy, Suspense, useState } from 'react';
import AuthScreen from './AuthScreen.jsx';
import ProcessingPanel from './ProcessingPanel.jsx';
import PreviewStudio, { ASPECTS } from './PreviewStudio.jsx';
import Shell from './Shell.jsx';
import { useI18n } from './i18n.jsx';
import useSession from './hooks/useSession.js';
import useRenderSettings from './hooks/useRenderSettings.js';
import useVideoJob from './hooks/useVideoJob.js';
import useVoicePlayback from './hooks/useVoicePlayback.js';

// Code-split: each of these is shown only after an action (a finished job, "see more voices", the usage sidebar page),
// never on first paint, so there's no reason to make every visitor download them before they've even picked a file.
// PreviewStudio stays a normal (eager) import above: it appears right after picking a video, too soon for a loading flicker to be worth it.
const Editor = lazy(() => import('./Editor.jsx'));
const VoiceLibrary = lazy(() => import('./VoiceLibrary.jsx'));
const UsageDashboard = lazy(() => import('./UsageDashboard.jsx'));

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

function App() {
  const { tr, trs } = useI18n();
  const [view, setView] = useState('create');   // sidebar page: create | usage
  const [usageKey, setUsageKey] = useState(0);   // bumped when a job ends so the usage page reloads
  const [showLibrary, setShowLibrary] = useState(false);

  const { signedIn, account, logout, onAuth, refreshAccount } = useSession();
  const settings = useRenderSettings();
  const {
    voiceType, setVoiceType, voiceGender, setVoiceGender, finish, setFinish, allowVoiceSpeedup, setAllowVoiceSpeedup,
    aspect, setAspect, fitMode, setFitMode, previewFx, changePreviewFx, fitTranslation, setFitTranslation,
    keepBackground, setKeepBackground, filmMode, setFilmMode, outputKind, setOutputKind, bgMode, setBgMode,
    emotionOn, setEmotionOn, softMusic, setSoftMusic,
  } = settings;
  const job = useVideoJob(settings, () => { refreshAccount(); setUsageKey((k) => k + 1); });
  const {
    videoFile, setVideoFile, customLogo, setCustomLogo, sourceUrl, loading, resultVideoUrl, resultDownloadUrl,
    subtitleUrl, errorMessage, notes, timeline, project, jobId, bgKept, upload, elapsed, progress, videoRef,
    handleGenerateRecap, cancelJob, applyEdits,
  } = job;
  const { voices, looks, playing, previewing, playSample, previewLine } = useVoicePlayback(jobId);

  if (signedIn === null) return <div className="min-h-screen bg-slate-950 p-6 text-slate-400">…</div>;
  if (!signedIn) return <AuthScreen onAuth={onAuth} />;

  return (
    <Shell view={view} setView={setView} account={account} onLogout={logout}>
      {showLibrary && (
        <Suspense fallback={null}>
          <VoiceLibrary voices={voices} looks={looks} selected={voiceType} playing={playing} onPlay={playSample}
            onSelect={(v) => { setVoiceType(v.name); setVoiceGender(v.gender); }} onClose={() => setShowLibrary(false)} apiBase={API_BASE} />
        </Suspense>
      )}
      <div className={view === 'create' ? '' : 'hidden'}>
      <div className="max-w-3xl mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">

        <form onSubmit={handleGenerateRecap} className="space-y-6">

          {/* Format first, then the video (like CapCut) */}
          <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
            <label className="block text-sm font-medium text-slate-300">{tr('Video format')}</label>
            <div className="flex flex-wrap gap-2">
              {[['original', tr('Original')], ['9:16', '9:16'], ['1:1', '1:1'], ['4:5', '4:5'], ['16:9', '16:9']].map(([k, label]) => {
                const [w, h] = ASPECTS[k] || [3, 4];
                const s = 26 / Math.max(w, h);
                return (
                  <button
                    key={k} type="button" onClick={() => setAspect(k)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-xl text-sm border ${aspect === k ? 'border-purple-400 bg-purple-600/30 text-white' : 'border-slate-700 bg-slate-800/50 text-slate-300'}`}
                  >
                    <span className={`inline-block border-2 rounded-sm ${aspect === k ? 'border-purple-300' : 'border-slate-500'}`} style={{ width: ASPECTS[k] ? w * s : 20, height: ASPECTS[k] ? h * s : 20, borderStyle: ASPECTS[k] ? 'solid' : 'dashed' }} />
                    {label}
                  </button>
                );
              })}
            </div>
            {aspect !== 'original' && (
              <div className="flex gap-4 text-sm text-slate-300 flex-wrap">
                {[['blur', tr('Fit (blurred background)')], ['crop', tr('Fill (crop)')]].map(([k, label]) => (
                  <label key={k} className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="fitMode" checked={fitMode === k} onChange={() => setFitMode(k)} className="accent-purple-500" />
                    {label}
                  </label>
                ))}
              </div>
            )}
            {!sourceUrl && (
              <div className="flex justify-center">
                <div
                  style={{ aspectRatio: ASPECTS[aspect] ? ASPECTS[aspect].join(' / ') : '16 / 9', width: ASPECTS[aspect] && ASPECTS[aspect][1] > ASPECTS[aspect][0] ? 'min(100%, 12rem)' : 'min(100%, 20rem)' }}
                  className="rounded-xl border border-dashed border-slate-600 flex items-center justify-center text-xs text-slate-500 text-center p-2"
                >
                  {tr('Choose a video to see it in this frame')}
                </div>
              </div>
            )}
          </div>

          {/* File Upload Section */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                {tr('Upload video')}
              </label>
              <input
                type="file"
                accept="video/*"
                onChange={(e) => setVideoFile(e.target.files[0])}
                className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-purple-600 file:text-white hover:file:bg-purple-500 cursor-pointer"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                {tr('Logo (optional)')}
              </label>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => setCustomLogo(e.target.files[0])}
                className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-slate-700 file:text-white hover:file:bg-slate-600 cursor-pointer"
              />
            </div>
          </div>

          {sourceUrl && !loading && !resultVideoUrl && (
            <PreviewStudio src={sourceUrl} logoFile={customLogo} fx={previewFx} onChange={changePreviewFx} />
          )}

          <div className="rounded-xl border border-purple-500/30 bg-purple-950/30 p-4">
            <p className="text-sm text-purple-200 mb-3">
              {tr('Burmese dialogue is translated by Google Gemini, then spoken naturally with Gemini TTS. Audio is not sped up to force-fit the source timing.')}
            </p>
            <div className="flex gap-2 mb-3">
              {['female', 'male'].map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setVoiceGender(g)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold capitalize ${
                    voiceGender === g ? 'bg-purple-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                  }`}
                >
                  {tr(g)}
                </button>
              ))}
            </div>
            {voices.length === 0 && (
              <p className="text-xs text-slate-400">{tr('No voice samples available: the default voice will be used.')}</p>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[...voices.filter((v) => v.gender === voiceGender).slice(0, 4), ...voices.filter((v) => v.gender === voiceGender).slice(4).filter((v) => v.name === voiceType)].map((v) => (
                <div
                  key={v.name}
                  className={`p-2 rounded-xl border transition-all ${
                    voiceType === v.name
                      ? 'border-purple-500 bg-purple-950/40 shadow-lg shadow-purple-900/20'
                      : 'border-slate-800 bg-slate-800/50 hover:bg-slate-800'
                  }`}
                >
                  <button type="button" onClick={() => setVoiceType(v.name)} className="w-full text-left">
                    <span className="font-semibold text-sm block">{v.name}</span>
                    <span className="text-xs text-purple-300 capitalize">{tr('{gender} Burmese voice', { gender: tr(v.gender) })}</span>
                  </button>
                  <div className="flex gap-3 mt-2 text-xs">
                    <button type="button" onClick={() => playSample(v)} className="text-purple-300 hover:text-white">
                      {playing === v.name ? tr('■ Stop') : tr('▶ Play')}
                    </button>
                    <a href={`${API_BASE}${v.sample_url}`} download className="text-slate-400 hover:text-white">
                      {tr('⬇ Download')}
                    </a>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" onClick={() => setShowLibrary(true)} className="mt-3 w-full py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm text-purple-200">
              {tr('See more voices ({n}) · search & categories →', { n: voices.length + looks.length })}
            </button>
          </div>

          {/* What kind of video is this? */}
          <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
            <div className="flex gap-2">
              {[['recap', tr('Recap video'), tr('One narrator voice')], ['full', tr('Full movie / drama'), tr('A voice for each character')]].map(([k, title, sub]) => (
                <button
                  key={k} type="button" onClick={() => setFilmMode(k)}
                  className={`flex-1 rounded-xl px-3 py-2 text-left border ${filmMode === k ? 'border-purple-400 bg-purple-600/30' : 'border-slate-700 bg-slate-800/50'}`}
                >
                  <span className="block text-sm font-semibold text-white">{title}</span>
                  <span className="block text-xs text-slate-400">{sub}</span>
                </button>
              ))}
            </div>
            <div className="text-sm text-slate-300">
                <div className="flex gap-4 flex-wrap">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'dub'} onChange={() => setOutputKind('dub')} className="accent-purple-500" />
                    {tr('Burmese voice-over + subtitles')}
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'subtitles'} onChange={() => setOutputKind('subtitles')} className="accent-purple-500" />
                    {tr('Burmese subtitles only (original sound stays)')}
                  </label>
                </div>
            </div>
            {filmMode === 'full' && (
              <div className="space-y-3 text-sm text-slate-300">
                <p className="text-xs text-slate-400">
                  {tr('Each character is detected and gets one fixed voice for the whole film (the main character uses the voice you pick below). The translation is rewritten as natural, neutral spoken Burmese, not word for word.')}
                </p>
                {outputKind === 'dub' && (
                  <>
                    <label className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                      <span>{tr('Original music & sounds')}</span>
                      <select value={bgMode} onChange={(e) => setBgMode(e.target.value)} className="w-full sm:w-auto min-w-0 sm:max-w-md rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-sm">
                        <option value="separate">{tr('Keep music & sound effects, remove the original speech (recommended)')}</option>
                        <option value="original">{tr('Keep everything, lowered (original speech stays faintly audible)')}</option>
                        <option value="off">{tr('Remove all original sound')}</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={emotionOn} onChange={(e) => setEmotionOn(e.target.checked)} className="w-4 h-4 accent-purple-500" />
                      {tr('Add emotion to the voices (angry, sad, scared…; a few key lines)')}
                    </label>
                  </>
                )}
              </div>
            )}
            <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
              <input type="checkbox" checked={softMusic} onChange={(e) => setSoftMusic(e.target.checked)} className="w-4 h-4 accent-purple-500" />
              {tr('Add a soft background tone (optional)')}
            </label>
          </div>

          {/* Sync policy + editing tools */}
          <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-4">
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={fitTranslation}
                onChange={(e) => setFitTranslation(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">
                {tr('Tighten long translations to fit each scene (uses Gemini; only the lines that overrun are rewritten)')}
              </span>
            </label>
            {filmMode === 'recap' && outputKind === 'dub' && <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={keepBackground}
                onChange={(e) => setKeepBackground(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">{tr('Keep original background music and effects (slower)')}</span>
            </label>}
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={allowVoiceSpeedup}
                onChange={(e) => setAllowVoiceSpeedup(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">
                {tr('Allow slight voice speed-up (up to 1.35x) before slowing the video')}
              </span>
            </label>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-4 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 font-bold rounded-xl shadow-lg transition-all transform active:scale-[0.99] disabled:opacity-50 cursor-pointer"
          >
            {loading ? tr('⚡ Processing…') : tr('✨ Generate video')}
          </button>
        </form>

        {loading && (
          <div className="mt-4">
            <div className="flex justify-between items-center text-xs text-slate-400 mb-1">
              <span>{trs(progress.stage)}</span>
              <span className="flex items-center gap-3">
                {progress.pct}%
                <button type="button" onClick={cancelJob} className="px-2 py-0.5 rounded bg-slate-700 hover:bg-red-800 text-slate-200">{tr('Cancel')}</button>
              </span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div className="h-full bg-purple-500 transition-all" style={{ width: `${progress.pct}%` }} />
            </div>
          </div>
        )}

        {/* Error Message */}
        {errorMessage && (
          <div className="mt-4 p-4 bg-red-950/50 border border-red-800 text-red-300 rounded-xl text-sm">
            {errorMessage}
          </div>
        )}

        {/* Preview & Download Section */}
        {(resultVideoUrl || (loading && sourceUrl)) && (
          <div className="mt-8 border-t border-slate-800 pt-6">
            <h2 className="text-lg font-semibold text-slate-200 mb-4">
              {tr('Preview & download')}
            </h2>
            <div className="flex flex-col items-center space-y-4">
              <div className="relative w-full max-w-xs min-h-[16rem]">
                <video
                  ref={videoRef}
                  src={resultVideoUrl || sourceUrl}
                  controls={!loading}
                  className="w-full rounded-xl border border-slate-800 shadow-lg"
                />
                {loading && (
                  <div className="absolute inset-0 rounded-xl bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center gap-3 p-4 text-center">
                    <div className="w-10 h-10 shrink-0 aspect-square rounded-full border-4 border-slate-700 border-t-purple-400 animate-spin" />
                    <p className="text-sm text-slate-200">{upload !== null && upload < 100 ? tr('Uploading {n}%', { n: upload }) : trs(progress.stage) || tr('Working…')}</p>
                    <div className="w-40 h-1.5 shrink-0 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-500 transition-all" style={{ width: `${upload !== null && upload < 100 ? upload : progress.pct}%` }} />
                    </div>
                    <button type="button" onClick={cancelJob} className="mt-1 px-4 py-1.5 shrink-0 rounded-full bg-slate-700 hover:bg-red-800 text-sm">
                      {tr('Cancel')}
                    </button>
                  </div>
                )}
              </div>
              {loading && <ProcessingPanel upload={upload} progress={progress} elapsed={elapsed} subsOnly={(project ? project.output : outputKind) === 'subtitles'} />}
              {resultVideoUrl && <a
                href={resultDownloadUrl}
                download
                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl text-sm transition-all shadow-md"
              >
                {tr('📥 Download video (MP4)')}
              </a>}
              {resultVideoUrl && <a
                href={subtitleUrl}
                download
                className="px-6 py-2.5 bg-slate-700 hover:bg-slate-600 text-white font-semibold rounded-xl text-sm transition-all"
              >
                {tr('Download subtitles (.srt)')}
              </a>}
              {notes && <p className="text-xs text-slate-400">{notes}</p>}
              {project && (
                <Suspense fallback={<p className="text-xs text-slate-400">{tr('Loading editor…')}</p>}>
                  <Editor key={jobId} project={project} videoRef={videoRef} busy={loading} voices={voices} looks={looks} playingVoice={playing} onPlaySample={playSample} onPreviewLine={previewLine} previewing={previewing} onApply={applyEdits} finish={finish} onFinish={(patch) => setFinish((f) => ({ ...f, ...patch }))} hasBackground={bgKept} />
                </Suspense>
              )}
              {!project && timeline.length > 0 && (
                <ul className="w-full text-xs text-slate-400 space-y-1">
                  {timeline.map((scene, i) => (
                    <li key={i}>
                      {scene.output_start.toFixed(1)}s · {scene.action}
                      {scene.action !== 'natural' && ` (source ${(scene.source_end - scene.source_start).toFixed(1)}s → ${scene.output_length.toFixed(1)}s)`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

      </div>
      </div>
      {view === 'usage' && (
        <Suspense fallback={<p className="p-6 text-sm text-slate-400">{tr('Loading…')}</p>}>
          <UsageDashboard apiBase={API_BASE} refreshKey={usageKey} />
        </Suspense>
      )}
    </Shell>
  );
}

export default App;
