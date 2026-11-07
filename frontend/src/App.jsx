import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Editor from './Editor.jsx';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

function AuthScreen({ onAuth }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await axios.post(`${API_BASE}/api/auth/${mode === 'login' ? 'login' : 'register'}`, { email, password });
      onAuth(data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not reach the server.');
    } finally {
      setBusy(false);
    }
  };

  const input = 'w-full rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-purple-500';
  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 font-sans flex items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
        <h1 className="text-xl font-bold text-purple-400">🎬 RedNote Recap Studio</h1>
        <input className={input} type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className={input} type="password" placeholder="Password (8+ characters)" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button disabled={busy} className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-500 font-semibold disabled:opacity-50">
          {mode === 'login' ? 'Log in' : 'Create account'}
        </button>
        <button type="button" onClick={() => setMode(mode === 'login' ? 'register' : 'login')} className="text-xs text-slate-400 hover:text-white">
          {mode === 'login' ? 'New here? Create an account' : 'Already have an account? Log in'}
        </button>
      </form>
    </div>
  );
}

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
function ProcessingPanel({ upload, progress, elapsed, subsOnly }) {
  const uploading = upload !== null && upload < 100;
  const pct = uploading ? -1 : progress.pct;
  return (
    <div className="w-full max-w-xs mt-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs">
      <div className="flex justify-between text-slate-400 mb-2">
        <span>Working on your video</span>
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
                {st.label}
                {active && <span className="block text-purple-300">{i === 0 ? `${upload}%` : progress.stage}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-[11px] text-slate-500">Longer videos can take a few minutes. You can cancel at any time.</p>
    </div>
  );
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [account, setAccount] = useState(null); // { email, daily_minutes, remaining_seconds }
  if (token) axios.defaults.headers.common.Authorization = `Bearer ${token}`;

  const logout = () => {
    localStorage.removeItem('token');
    delete axios.defaults.headers.common.Authorization;
    setToken('');
    setAccount(null);
  };
  const onAuth = (data) => {
    localStorage.setItem('token', data.token);
    axios.defaults.headers.common.Authorization = `Bearer ${data.token}`;
    setToken(data.token);
    setAccount(data);
  };
  const refreshAccount = () => axios.get(`${API_BASE}/api/auth/me`).then((r) => setAccount(r.data)).catch(() => {});
  useEffect(() => {
    const id = axios.interceptors.response.use((r) => r, (err) => {
      if (err.response?.status === 401 && !String(err.config?.url).includes('/api/auth/')) logout();
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []);
  useEffect(() => { if (token) refreshAccount(); }, [token]);
  const absUrl = (u) => (u.startsWith('http') ? u : API_BASE + u);

  // Form State
  const [videoFile, setVideoFile] = useState(null);
  const [customLogo, setCustomLogo] = useState(null);
  const [voiceType, setVoiceType] = useState('Kore');
  const [voices, setVoices] = useState([]);
  const [voiceGender, setVoiceGender] = useState('female');
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    axios.get(`${API_BASE}/api/voices`).then((r) => setVoices(r.data)).catch(() => setVoices([]));
    return () => audioRef.current?.pause();
  }, []);

  const playSample = (voice) => {
    audioRef.current?.pause();
    if (playing === voice.name) {
      setPlaying(null);
      return;
    }
    const audio = new Audio(`${API_BASE}${voice.sample_url}`);
    audio.onended = () => setPlaying(null);
    audio.play();
    audioRef.current = audio;
    setPlaying(voice.name);
  };
  // Feature Toggles
  const [blurSubtitles, setBlurSubtitles] = useState(true);
  const [enableSubtitles, setEnableSubtitles] = useState(true); // Burmese Subtitles toggle
  const [removeWatermark, setRemoveWatermark] = useState(true);
  const [enableFlip, setEnableFlip] = useState(true);
  const [flipVertical, setFlipVertical] = useState(false);
  // Sync policy: by default the voice is never sped up; the video slows/freezes to fit it.
  const [allowVoiceSpeedup, setAllowVoiceSpeedup] = useState(true);
  // Grading & speed
  const [videoSpeed, setVideoSpeed] = useState(1);
  const [brightness, setBrightness] = useState(0);
  const [contrast, setContrast] = useState(1);
  const [saturation, setSaturation] = useState(1);
  const [logoPosition, setLogoPosition] = useState('top-right');
  const [fitTranslation, setFitTranslation] = useState(true);
  const [keepBackground, setKeepBackground] = useState(false);
  const [filmMode, setFilmMode] = useState('recap'); // 'recap' = one narrator voice | 'full' = characters with their own voices
  const [outputKind, setOutputKind] = useState('dub'); // 'dub' = Burmese voice-over | 'subtitles' = keep original sound, subtitles only
  const [bgMode, setBgMode] = useState('original'); // full mode: keep the film's own music and sounds ('original' | 'separate' | 'off')
  const [emotionOn, setEmotionOn] = useState(true);
  const [softMusic, setSoftMusic] = useState(false);
  const [progress, setProgress] = useState({ pct: 0, stage: '' });
  const [notes, setNotes] = useState('');
  const [subtitleUrl, setSubtitleUrl] = useState('');
  const [timeline, setTimeline] = useState([]);
  const [project, setProject] = useState(null); // editable lines of the finished job
  const [jobId, setJobId] = useState('');
  const videoRef = useRef(null);
  const activeJob = useRef('');
  const [upload, setUpload] = useState(null); // % uploaded while the video is being sent
  const [elapsed, setElapsed] = useState(0);
  const [sourceUrl, setSourceUrl] = useState('');
  const cancelled = useRef(false);

  // UI Processing & Result State
  const [loading, setLoading] = useState(false);
  const [resultVideoUrl, setResultVideoUrl] = useState('');
  const [resultDownloadUrl, setResultDownloadUrl] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    if (!videoFile) { setSourceUrl(''); return undefined; }
    const url = URL.createObjectURL(videoFile);
    setSourceUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [videoFile]);
  useEffect(() => {
    if (!loading) return undefined;
    setElapsed(0);
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [loading]);

  // Handle Form Submission
  const handleGenerateRecap = async (e) => {
    e.preventDefault();
    if (!videoFile) {
      alert('ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် ရွေးချယ်ပေးပါ (Please select a video file)');
      return;
    }

    cancelled.current = false;
    activeJob.current = '';
    setLoading(true);
    setErrorMessage('');
    setNotes('');
    setResultVideoUrl('');
    setTimeline([]);
    setProject(null);

    const formData = new FormData();
    formData.append('video_file', videoFile);
    if (customLogo) formData.append('custom_logo', customLogo);
    formData.append('voice_type', voiceType);
    formData.append('target_language', 'my');
    formData.append('blur_subtitles', blurSubtitles);
    formData.append('enable_subtitles', enableSubtitles); // Sent to FastAPI backend
    formData.append('remove_watermark', removeWatermark);
    formData.append('enable_flip', enableFlip);
    formData.append('flip_vertical', flipVertical);
    formData.append('allow_voice_speedup', allowVoiceSpeedup);
    formData.append('video_speed', videoSpeed);
    formData.append('brightness', brightness);
    formData.append('contrast', contrast);
    formData.append('saturation', saturation);
    formData.append('logo_position', logoPosition);
    formData.append('fit_translation', fitTranslation);
    formData.append('keep_background', keepBackground);
    formData.append('mode', filmMode);
    formData.append('output', filmMode === 'full' ? outputKind : 'dub');
    if (filmMode === 'full') formData.append('background', bgMode);
    formData.append('emotion', emotionOn);
    formData.append('soft_music', softMusic);

    try {
      setUpload(0);
      setProgress({ pct: 0, stage: 'Uploading' });
      const { data: started } = await axios.post(`${API_BASE}/api/jobs`, formData, {
        onUploadProgress: (e) => e.total && setUpload(Math.round((100 * e.loaded) / e.total)),
      });
      setUpload(null);
      setProgress({ pct: 0, stage: 'Queued' });
      await followJob(started.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
      setUpload(null);
      refreshAccount();
    }
  };

  const cancelJob = async () => {
    cancelled.current = true;
    if (activeJob.current) {
      try { await axios.post(`${API_BASE}/api/jobs/${activeJob.current}/cancel`); } catch (e) { /* the loop below stops anyway */ }
    }
  };

  const showError = (error) => {
    if (error.cancelled) {
      setErrorMessage('');
      setNotes(resultVideoUrl ? 'Cancelled. Your previous video is unchanged.' : '');
      return;
    }
    console.error('Processing error:', error);
    setErrorMessage(error.response?.data?.detail || error.message || 'ဗီဒီယို ထုတ်လုပ်ရာတွင် အမှားအယွင်း ရှိသွားပါသည်');
  };

  // Poll a job until it finishes, then show its result (used for new videos and for editor re-renders).
  const followJob = async (id) => {
    let job;
    activeJob.current = id;
    const stopped = () => Object.assign(new Error('Cancelled'), { cancelled: true });
    if (cancelled.current) { await cancelJob(); throw stopped(); } // Cancel was pressed while the job was being created
    do {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (cancelled.current) throw stopped();
      ({ data: job } = await axios.get(`${API_BASE}/api/jobs/${id}`));
      const waiting = job.status === 'queued' && job.queue_position
        ? `Waiting in line: you are #${job.queue_position}${job.eta_seconds ? `, about ${Math.max(1, Math.ceil(job.eta_seconds / 60))} min` : ', starting soon'}`
        : job.stage;
      setProgress({ pct: job.progress, stage: waiting });
    } while (job.status === 'running' || job.status === 'queued');

    if (job.status === 'cancelled') throw stopped();
    if (job.status === 'error') throw new Error(job.error);
    const result = job.result;
    if (result.expired) throw new Error('This result has expired. Please generate it again.');
    setResultVideoUrl(absUrl(result.video_url));
    setResultDownloadUrl(absUrl(result.download_url));
    setSubtitleUrl(absUrl(result.subtitle_url));
    setTimeline(result.timeline.filter((scene) => scene.text));
    setProject(result.project || null);
    setJobId(job.id);
    setNotes(
      [
        result.subtitles_detected ? 'Source subtitles detected and blurred.' : 'No source subtitles found, nothing blurred.',
        keepBackground && !result.background_kept ? 'Background music separation failed; voice-only audio.' : '',
        ...(result.warnings || []),
      ].filter(Boolean).join(' ')
    );
  };

  const applyEdits = async (lines, speakerVoices) => {
    cancelled.current = false;
    activeJob.current = '';
    setLoading(true);
    setErrorMessage('');
    setNotes('');
    try {
      const { data } = await axios.post(`${API_BASE}/api/jobs/${jobId}/rerender`, { segments: lines, speaker_voices: speakerVoices || undefined });
      setProgress({ pct: 0, stage: 'Queued' });
      await followJob(data.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  if (!token) return <AuthScreen onAuth={onAuth} />;

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 font-sans">
      <div className="max-w-3xl mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
        
        {/* Header */}
        <h1 className="text-2xl font-bold mb-2 text-purple-400 flex items-center gap-2">
          🎬 RedNote Recap Studio (မြန်မာ)
        </h1>
        {account && (
          <div className="flex items-center justify-between text-xs text-slate-400 mb-6">
            <span>
              {account.email} · {Math.floor(account.remaining_seconds / 60)} of {account.daily_minutes} min left today
            </span>
            <button type="button" onClick={logout} className="hover:text-white">Log out</button>
          </div>
        )}

        <form onSubmit={handleGenerateRecap} className="space-y-6">
          
          {/* File Upload Section */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                ဗီဒီယိုဖိုင် တင်ရန် (Upload Video)
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
                လိုဂို ရွေးချယ်ရန် (Optional Logo)
              </label>
              <input
                type="file"
                accept="image/*"
                onChange={(e) => setCustomLogo(e.target.files[0])}
                className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-slate-700 file:text-white hover:file:bg-slate-600 cursor-pointer"
              />
            </div>
          </div>

          <div className="rounded-xl border border-purple-500/30 bg-purple-950/30 p-4">
            <p className="text-sm text-purple-200 mb-3">
              Burmese dialogue is translated by Google Gemini, then spoken naturally with Gemini TTS. Audio is not sped up to force-fit the source timing.
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
                  {g}
                </button>
              ))}
            </div>
            {voices.length === 0 && (
              <p className="text-xs text-slate-400">No voice samples available — the default voice will be used.</p>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {voices.filter((v) => v.gender === voiceGender).map((v) => (
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
                    <span className="text-xs text-purple-300 capitalize">{v.gender} Burmese voice</span>
                  </button>
                  <div className="flex gap-3 mt-2 text-xs">
                    <button type="button" onClick={() => playSample(v)} className="text-purple-300 hover:text-white">
                      {playing === v.name ? '■ Stop' : '▶ Play'}
                    </button>
                    <a href={`${API_BASE}${v.sample_url}`} download className="text-slate-400 hover:text-white">
                      ⬇ Download
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Feature Toggles (Checkboxes) */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-2">
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={blurSubtitles}
                onChange={(e) => setBlurSubtitles(e.target.checked)}
                className="w-4 h-4 text-purple-600 rounded accent-purple-500"
              />
              <span className="text-sm text-slate-300">Blur Subtitles</span>
            </label>

            {/* New Burmese Subtitles Toggle */}
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={enableSubtitles}
                onChange={(e) => setEnableSubtitles(e.target.checked)}
                className="w-4 h-4 text-purple-600 rounded accent-purple-500"
              />
              <span className="text-sm text-purple-300 font-medium">မြန်မာစာတန်းထိုး (Subtitles)</span>
            </label>

            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={removeWatermark}
                onChange={(e) => setRemoveWatermark(e.target.checked)}
                className="w-4 h-4 text-purple-600 rounded accent-purple-500"
              />
              <span className="text-sm text-slate-300">Blur Lower-Right Watermark</span>
            </label>

            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={enableFlip}
                onChange={(e) => setEnableFlip(e.target.checked)}
                className="w-4 h-4 text-purple-600 rounded accent-purple-500"
              />
              <span className="text-sm text-slate-300">Horizontal Flip</span>
            </label>

            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={flipVertical}
                onChange={(e) => setFlipVertical(e.target.checked)}
                className="w-4 h-4 text-purple-600 rounded accent-purple-500"
              />
              <span className="text-sm text-slate-300">Vertical Flip</span>
            </label>
          </div>

          {/* What kind of video is this? */}
          <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
            <div className="flex gap-2">
              {[['recap', 'Recap video', 'One narrator voice'], ['full', 'Full movie / drama', 'A voice for each character']].map(([k, title, sub]) => (
                <button
                  key={k} type="button" onClick={() => setFilmMode(k)}
                  className={`flex-1 rounded-xl px-3 py-2 text-left border ${filmMode === k ? 'border-purple-400 bg-purple-600/30' : 'border-slate-700 bg-slate-800/50'}`}
                >
                  <span className="block text-sm font-semibold text-white">{title}</span>
                  <span className="block text-xs text-slate-400">{sub}</span>
                </button>
              ))}
            </div>
            {filmMode === 'full' && (
              <div className="space-y-3 text-sm text-slate-300">
                <p className="text-xs text-slate-400">
                  Each character is detected and gets one fixed voice for the whole film (the main character uses the voice you pick below).
                  The translation is rewritten as natural, neutral spoken Burmese, not word for word.
                </p>
                <div className="flex gap-4 flex-wrap">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'dub'} onChange={() => setOutputKind('dub')} className="accent-purple-500" />
                    Burmese voice-over + subtitles
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'subtitles'} onChange={() => setOutputKind('subtitles')} className="accent-purple-500" />
                    Burmese subtitles only (original sound stays)
                  </label>
                </div>
                {outputKind === 'dub' && (
                  <>
                    <label className="flex items-center gap-2">
                      <span>Original music &amp; sounds</span>
                      <select value={bgMode} onChange={(e) => setBgMode(e.target.value)} className="rounded-lg bg-slate-900 border border-slate-700 px-2 py-1 text-sm">
                        <option value="original">Keep, lowered under the voice (fast)</option>
                        <option value="separate">Keep music only, remove original speech (slow)</option>
                        <option value="off">Remove</option>
                      </select>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={emotionOn} onChange={(e) => setEmotionOn(e.target.checked)} className="w-4 h-4 accent-purple-500" />
                      Add emotion to the voices (angry, sad, scared…; a few key lines)
                    </label>
                  </>
                )}
              </div>
            )}
            <label className="flex items-center gap-2 cursor-pointer text-sm text-slate-300">
              <input type="checkbox" checked={softMusic} onChange={(e) => setSoftMusic(e.target.checked)} className="w-4 h-4 accent-purple-500" />
              Add a soft background tone (optional)
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
                Tighten long translations to fit each scene (uses Gemini; only the lines that overrun are rewritten)
              </span>
            </label>
            {filmMode === 'recap' && <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={keepBackground}
                onChange={(e) => setKeepBackground(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">Keep original background music and effects (slower)</span>
            </label>}
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={allowVoiceSpeedup}
                onChange={(e) => setAllowVoiceSpeedup(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">
                Allow slight voice speed-up (up to 1.35x) before slowing the video
              </span>
            </label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              {[
                ['Video speed', videoSpeed, setVideoSpeed, 0.5, 2, 0.05],
                ['Brightness', brightness, setBrightness, -0.5, 0.5, 0.05],
                ['Contrast', contrast, setContrast, 0.5, 1.5, 0.05],
                ['Saturation', saturation, setSaturation, 0, 2, 0.05],
              ].map(([label, value, setter, min, max, step]) => (
                <label key={label} className="text-xs text-slate-400">
                  {label}: <span className="text-slate-200">{Number(value).toFixed(2)}</span>
                  <input
                    type="range"
                    min={min}
                    max={max}
                    step={step}
                    value={value}
                    onChange={(e) => setter(Number(e.target.value))}
                    className="w-full accent-purple-500"
                  />
                </label>
              ))}
              <label className="text-xs text-slate-400">
                Logo position
                <select
                  value={logoPosition}
                  onChange={(e) => setLogoPosition(e.target.value)}
                  className="mt-1 w-full bg-slate-800 border border-slate-700 rounded-lg p-1.5 text-slate-200"
                >
                  {['top-right', 'top-left', 'bottom-right', 'bottom-left', 'center'].map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-4 bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 font-bold rounded-xl shadow-lg transition-all transform active:scale-[0.99] disabled:opacity-50 cursor-pointer"
          >
            {loading ? '⚡ ဗီဒီယို ထုတ်လုပ်နေသည် (Processing...) ...' : '✨ အသံနှင့် ဗီဒီယို ထုတ်ယူမည် (Generate Recap)'}
          </button>
        </form>

        {loading && (
          <div className="mt-4">
            <div className="flex justify-between items-center text-xs text-slate-400 mb-1">
              <span>{progress.stage}</span>
              <span className="flex items-center gap-3">
                {progress.pct}%
                <button type="button" onClick={cancelJob} className="px-2 py-0.5 rounded bg-slate-700 hover:bg-red-800 text-slate-200">Cancel</button>
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
              ၄။ ဗီဒီယို ကြည့်ရှုရန် နှင့် ဒေါင်းလုပ်လုပ်ရန် (Preview & Download)
            </h2>
            <div className="flex flex-col items-center space-y-4">
              <div className="relative w-full max-w-xs">
                <video
                  ref={videoRef}
                  src={resultVideoUrl || sourceUrl}
                  controls={!loading}
                  className="w-full rounded-xl border border-slate-800 shadow-lg"
                />
                {loading && (
                  <div className="absolute inset-0 rounded-xl bg-slate-950/80 backdrop-blur-sm flex flex-col items-center justify-center gap-3 p-4 text-center">
                    <div className="w-10 h-10 rounded-full border-4 border-slate-700 border-t-purple-400 animate-spin" />
                    <p className="text-sm text-slate-200">{upload !== null && upload < 100 ? `Uploading ${upload}%` : progress.stage || 'Working…'}</p>
                    <div className="w-40 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-500 transition-all" style={{ width: `${upload !== null && upload < 100 ? upload : progress.pct}%` }} />
                    </div>
                    <button type="button" onClick={cancelJob} className="mt-1 px-4 py-1.5 rounded-full bg-slate-700 hover:bg-red-800 text-sm">
                      Cancel
                    </button>
                  </div>
                )}
              </div>
              {loading && <ProcessingPanel upload={upload} progress={progress} elapsed={elapsed} subsOnly={(project ? project.output : (filmMode === 'full' ? outputKind : 'dub')) === 'subtitles'} />}
              {resultVideoUrl && <a
                href={resultDownloadUrl}
                download
                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl text-sm transition-all shadow-md"
              >
                📥 ဗီဒီယို သိမ်းဆည်းမည် (Download MP4)
              </a>}
              {resultVideoUrl && <a
                href={subtitleUrl}
                download
                className="px-6 py-2.5 bg-slate-700 hover:bg-slate-600 text-white font-semibold rounded-xl text-sm transition-all"
              >
                Download subtitles (.srt)
              </a>}
              {notes && <p className="text-xs text-slate-400">{notes}</p>}
              {project && (
                <Editor key={jobId} project={project} videoRef={videoRef} busy={loading} voices={voices} onApply={applyEdits} />
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
  );
}

export default App;
