import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Editor from './Editor.jsx';
import VoiceLibrary from './VoiceLibrary.jsx';
import Select from './Select.jsx';
import PreviewStudio, { ASPECTS } from './PreviewStudio.jsx';
import Shell from './Shell.jsx';
import UsageDashboard from './UsageDashboard.jsx';
import HistoryPage from './HistoryPage.jsx';
import TopUpPage from './TopUpPage.jsx';
import { LangSwitch, useI18n } from './i18n.jsx';
import { deviceCapability, renderFromPlan } from './deviceRenderPlan.js';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

// A random id this browser keeps, so the owner's "one device per login" rule can tell devices apart.
const deviceId = () => {
  try {
    let id = localStorage.getItem('device_id');
    if (!id) { id = (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, ''); localStorage.setItem('device_id', id); }
    return id;
  } catch { return 'unknown'; }
};

// Glossy "3D" icons for the two modes (inline SVG, gradients + highlights + soft shadow)
function RecapIcon() {   // clapperboard
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16 drop-shadow-[0_6px_6px_rgba(0,0,0,0.45)]" aria-hidden="true">
      <defs>
        <linearGradient id="rc-body" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#7c8aa5" /><stop offset="1" stopColor="#2b3447" /></linearGradient>
        <linearGradient id="rc-top" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#f0abfc" /><stop offset="1" stopColor="#7e22ce" /></linearGradient>
        <linearGradient id="rc-play" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#ffffff" /><stop offset="1" stopColor="#d8b4fe" /></linearGradient>
      </defs>
      <rect x="6" y="26" width="52" height="30" rx="5" fill="url(#rc-body)" />
      <rect x="6" y="26" width="52" height="5" rx="2" fill="#ffffff" opacity="0.18" />
      <path d="M6 12 L58 5 L60 17 L8 24 Z" fill="url(#rc-top)" />
      <path d="M16 10.7 L24 9.6 L18 22.4 L10 23.4 Z M32 8.5 L40 7.4 L34 20.2 L26 21.3 Z M48 6.3 L56 5.2 L50 18 L42 19.1 Z" fill="#1e1b4b" opacity="0.55" />
      <path d="M6 24 L58 17 L58 24 L6 28 Z" fill="#4c1d95" />
      <path d="M26 33 L26 51 L42 42 Z" fill="url(#rc-play)" />
      <path d="M26 33 L34 37.5 L26 42 Z" fill="#fff" opacity="0.5" />
    </svg>
  );
}
function MovieIcon() {   // film reel on a base
  return (
    <svg viewBox="0 0 64 64" className="h-16 w-16 drop-shadow-[0_6px_6px_rgba(0,0,0,0.45)]" aria-hidden="true">
      <defs>
        <radialGradient id="mv-disc" cx="0.35" cy="0.3" r="0.9"><stop offset="0" stopColor="#fde68a" /><stop offset="0.55" stopColor="#f59e0b" /><stop offset="1" stopColor="#b45309" /></radialGradient>
        <radialGradient id="mv-hole" cx="0.4" cy="0.35" r="0.8"><stop offset="0" stopColor="#475569" /><stop offset="1" stopColor="#0f172a" /></radialGradient>
        <linearGradient id="mv-base" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#64748b" /><stop offset="1" stopColor="#1e293b" /></linearGradient>
      </defs>
      <ellipse cx="32" cy="58" rx="20" ry="3.5" fill="#000" opacity="0.35" />
      <rect x="18" y="50" width="28" height="8" rx="4" fill="url(#mv-base)" />
      <circle cx="32" cy="29" r="24" fill="url(#mv-disc)" />
      <ellipse cx="25" cy="15" rx="12" ry="6" fill="#fff" opacity="0.35" transform="rotate(-25 25 15)" />
      {[[32, 14], [46, 29], [32, 44], [18, 29]].map(([x, y]) => <circle key={`${x}-${y}`} cx={x} cy={y} r="6.2" fill="url(#mv-hole)" />)}
      <circle cx="32" cy="29" r="5" fill="#7c2d12" /><circle cx="32" cy="29" r="2.2" fill="#fde68a" />
      <circle cx="32" cy="29" r="24" fill="none" stroke="#fff" strokeOpacity="0.25" strokeWidth="1.2" />
    </svg>
  );
}

function AuthScreen({ onAuth, notice }) {
  const { tr, trs } = useI18n();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const { data } = await axios.post(`${API_BASE}/api/auth/login`, { email: username.trim(), password, device_id: deviceId() });
      onAuth(data);
    } catch (err) {
      setError(trs(err.response?.data?.detail) || tr('Could not reach the server.'));
    } finally {
      setBusy(false);
    }
  };

  const input = 'w-full rounded-xl bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white outline-none focus:border-purple-500';
  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 font-sans flex items-center justify-center">
      <form onSubmit={submit} className="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between"><h1 className="text-xl font-bold text-purple-400">🎬 Movie Recap Tool</h1><LangSwitch /></div>
        {notice && !error && <p className="text-sm text-amber-300">{trs(notice)}</p>}
        <input className={input} type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder={tr('Username')} value={username} onChange={(e) => setUsername(e.target.value)} required />
        <input className={input} type="password" autoComplete="current-password" placeholder={tr('Password')} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button disabled={busy} className="w-full py-2 rounded-xl bg-purple-600 hover:bg-purple-500 font-semibold disabled:opacity-50">{tr('Log in')}</button>
        <p className="text-xs text-slate-500">{tr('Your username and password are given to you by the admin.')}</p>
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

function App() {
  const { tr, trs } = useI18n();
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [view, setView] = useState('create');   // sidebar page: create | usage
  const [usageKey, setUsageKey] = useState(0);   // bumped when a job ends so the usage page reloads
  const [account, setAccount] = useState(null); // { email, daily_minutes, remaining_seconds }
  const [notice, setNotice] = useState('');   // why the user was signed out (paused, device removed, ...)
  if (token) axios.defaults.headers.common.Authorization = `Bearer ${token}`;

  const logout = (why) => {
    setNotice(typeof why === 'string' ? why : '');
    localStorage.removeItem('token');
    delete axios.defaults.headers.common.Authorization;
    setToken('');
    setAccount(null);
  };
  const onAuth = (data) => {
    localStorage.setItem('token', data.token);
    axios.defaults.headers.common.Authorization = `Bearer ${data.token}`;
    setNotice('');
    setToken(data.token);
    setAccount(data);
  };
  const refreshAccount = () => axios.get(`${API_BASE}/api/auth/me`).then((r) => setAccount(r.data)).catch(() => {});
  useEffect(() => {
    const id = axios.interceptors.response.use((r) => r, (err) => {
      if (err.response?.status === 401 && !String(err.config?.url).includes('/api/auth/')) logout(err.response?.data?.detail);
      return Promise.reject(err);
    });
    return () => axios.interceptors.response.eject(id);
  }, []);
  useEffect(() => { if (token) refreshAccount(); }, [token]);
  const absUrl = (u) => (u.startsWith('http') ? u : API_BASE + u);

  // Form State
  const [videoFile, setVideoFile] = useState(null);
  const [customLogo, setCustomLogo] = useState(null);
  const [logoInputKey, setLogoInputKey] = useState(0); // changing it empties the file input (a chosen file cannot be cleared otherwise)
  const [voiceType, setVoiceType] = useState('Kore');
  const [voices, setVoices] = useState([]);
  const [looks, setLooks] = useState([]);
  const [showLibrary, setShowLibrary] = useState(false);
  const [voiceGender, setVoiceGender] = useState('female');
  const [voiceQuality, setVoiceQuality] = useState('premium'); // 'premium' = Gemini (30 voices, emotion) | 'standard' = Azure (2 voices, cheaper, more usage)
  const [standardOk, setStandardOk] = useState(false);
  const standard = voiceQuality === 'standard' && standardOk;
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    axios.get(`${API_BASE}/api/voices`).then((r) => setVoices(r.data)).catch(() => setVoices([]));
    axios.get(`${API_BASE}/api/looks`).then((r) => setLooks(r.data)).catch(() => setLooks([]));
    axios.get(`${API_BASE}/api/voice-quality`).then((r) => setStandardOk(!!r.data.standard)).catch(() => setStandardOk(false));
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
  const [previewing, setPreviewing] = useState(null);
  const previewLine = async (line, voiceName) => {
    if (!jobId) return;
    audioRef.current?.pause();
    setPreviewing(line.key);
    try {
      const { data } = await axios.post(`${API_BASE}/api/jobs/${jobId}/preview-line`, { id: line.id ?? null, text: line.text, voice: voiceName }, { responseType: 'blob', timeout: 120000 });
      const audio = new Audio(URL.createObjectURL(data));
      audioRef.current = audio;
      audio.play();
    } catch (err) {
      let msg = err.message;
      try { msg = JSON.parse(await err.response.data.text()).detail || msg; } catch { /* keep */ }
      window.alert(trs(msg));
    } finally {
      setPreviewing(null);
    }
  };
  // Feature Toggles
  // Finishing settings: not in the form any more, edited in the editor AFTER the first result (they re-render the video).
  const [finish, setFinish] = useState({ blur_subtitles: true, enable_subtitles: true, remove_watermark: false, enable_flip: false, bg_volume: null });
  const [bgKept, setBgKept] = useState(false);   // the result has the film's own music/effects under the voice
  // Sync policy: by default the voice is never sped up; the video slows/freezes to fit it.
  const [allowVoiceSpeedup, setAllowVoiceSpeedup] = useState(true);
  // Grading & speed
  const [videoSpeed, setVideoSpeed] = useState(1);
  const [brightness, setBrightness] = useState(0);
  const [contrast, setContrast] = useState(1);
  const [saturation, setSaturation] = useState(1);
  const [logoPosition, setLogoPosition] = useState('top-right');
  const [logoSize, setLogoSize] = useState(0.15);
  const [logoXY, setLogoXY] = useState(null); // dragged position in the preview (fractions of the frame); null = use logoPosition
  const [blurBoxes, setBlurBoxes] = useState([]); // user blur boxes, DISPLAYED coordinates (fractions)
  const [deviceCap, setDeviceCap] = useState(null);     // can this phone/browser draw the video itself? (WebCodecs + WebGL + speed test)
  const [useDevice, setUseDevice] = useState(false);     // "Render on my device (faster, beta)"
  const [queue, setQueue] = useState(null);              // server queue: { busy, wait_seconds }
  const lastDevice = useRef(false);                      // the shown result was drawn on this device (re-renders then do the same)
  useEffect(() => { deviceCapability().then(setDeviceCap).catch(() => {}); }, []);
  useEffect(() => {
    if (!token || !deviceCap?.ok) return undefined;
    const load = () => axios.get(`${API_BASE}/api/queue`).then((r) => setQueue(r.data)).catch(() => {});
    load();
    const id = setInterval(load, 20000);
    return () => clearInterval(id);
  }, [token, deviceCap]);
  const [resolution, setResolution] = useState('720'); // output size: 720 renders faster (recommended)
  const [aspect, setAspect] = useState('original'); // output format, chosen BEFORE uploading (like CapCut)
  const [fitMode, setFitMode] = useState('blur');     // 'blur' = whole picture over a blurred copy | 'crop' = fill the frame
  const [pan, setPan] = useState({ x: 0.5, y: 0.5 });  // crop mode: which part of the picture stays
  const previewFx = { videoSpeed, brightness, contrast, saturation, logoSize, logoPosition, logoXY, blurBoxes, flip: false,
    aspect, fitMode, panX: pan.x, panY: pan.y };
  const removeLogo = () => { setCustomLogo(null); setLogoXY(null); setLogoInputKey((k) => k + 1); };
  const changePreviewFx = (patch) => {
    if (patch.removeLogo) { removeLogo(); return; }
    const set = { videoSpeed: setVideoSpeed, brightness: setBrightness, contrast: setContrast, saturation: setSaturation,
      logoSize: setLogoSize, logoPosition: setLogoPosition, logoXY: setLogoXY, blurBoxes: setBlurBoxes };
    if ('panX' in patch) setPan((p) => ({ ...p, x: patch.panX }));
    if ('panY' in patch) setPan((p) => ({ ...p, y: patch.panY }));
    Object.entries(patch).forEach(([k, v]) => set[k]?.(v));
  };
  const [fitTranslation, setFitTranslation] = useState(true);
  const [keepBackground, setKeepBackground] = useState(false);
  const [filmMode, setFilmMode] = useState('recap'); // 'recap' = one narrator voice | 'full' = characters with their own voices
  const [outputKind, setOutputKind] = useState('dub'); // 'dub' = Burmese voice-over | 'subtitles' = keep original sound, subtitles only
  const [bgMode, setBgMode] = useState('separate'); // full mode: the film's own sounds ('separate' = effects kept, speech removed | 'original' = all lowered | 'off')
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
      alert(tr('Please select a video file.'));
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
    formData.append('voice_quality', standard ? 'standard' : 'premium');
    formData.append('target_language', 'my');
    formData.append('blur_subtitles', finish.blur_subtitles);
    formData.append('enable_subtitles', finish.enable_subtitles);
    formData.append('remove_watermark', finish.remove_watermark);
    formData.append('enable_flip', finish.enable_flip);
    if (finish.bg_volume != null) formData.append('bg_volume', finish.bg_volume);
    formData.append('allow_voice_speedup', allowVoiceSpeedup);
    formData.append('video_speed', videoSpeed);
    formData.append('brightness', brightness);
    formData.append('contrast', contrast);
    formData.append('saturation', saturation);
    formData.append('logo_position', logoPosition);
    formData.append('logo_size', logoSize);
    if (customLogo && logoXY) {
      formData.append('logo_x', logoXY[0]);
      formData.append('logo_y', logoXY[1]);
    }
    // Boxes are in the output frame as shown (the render applies them after reframe and flip).
    formData.append('manual_blurs', JSON.stringify(blurBoxes.map((b) => [b.x, b.y, b.w, b.h])));
    formData.append('resolution', resolution);
    formData.append('device_render', !!(useDevice && deviceCap?.ok));
    formData.append('aspect', aspect);
    formData.append('fit_mode', fitMode);
    formData.append('pan_x', pan.x);
    formData.append('pan_y', pan.y);
    formData.append('fit_translation', fitTranslation);
    formData.append('keep_background', keepBackground);
    formData.append('mode', filmMode);
    formData.append('output', outputKind);
    if (filmMode === 'full') formData.append('background', bgMode);
    formData.append('emotion', emotionOn);
    formData.append('soft_music', softMusic);

    try {
      setUpload(0);
      setProgress({ pct: 0, stage: tr('Uploading') });
      const { data: started } = await axios.post(`${API_BASE}/api/jobs`, formData, {
        onUploadProgress: (e) => e.total && setUpload(Math.round((100 * e.loaded) / e.total)),
      });
      setUpload(null);
      setProgress({ pct: 0, stage: tr('Queued') });
      await followJob(started.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
      setUpload(null);
      refreshAccount();
      setUsageKey((k) => k + 1);
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
      setNotes(resultVideoUrl ? tr('Cancelled. Your previous video is unchanged.') : '');
      return;
    }
    console.error('Processing error:', error);
    setErrorMessage(trs(error.response?.data?.detail || error.message) || tr('Something went wrong while making the video.'));
  };

  // Draw the video on this device from the server's plan. Returns the video's blob URL, or null after handing the job to the server.
  const finishOnDevice = async (job, result) => {
    const signal = { aborted: false };
    const onHide = () => { if (document.hidden) signal.aborted = true; };   // iOS pauses the page in the background: the decoder dies
    let lock = null, ok = false, error = '', stats = null;
    const t0 = Date.now();
    try {
      if (!videoFile) throw new Error('The original video is not on this device any more');
      setProgress({ pct: 0, stage: tr('Making the picture on your device: keep this screen open') });
      document.addEventListener('visibilitychange', onHide);
      try { lock = await navigator.wakeLock?.request('screen'); } catch (e) { /* optional */ }
      const audioBlob = await (await fetch(absUrl(result.audio_url))).blob();
      const run = () => renderFromPlan(videoFile, result.device_plan, audioBlob, customLogo, {
        signal,
        onProgress: (p) => { if (cancelled.current) signal.aborted = true; setProgress({ pct: Math.round(p * 100), stage: tr('Making the picture on your device: keep this screen open') }); },
      });
      let out;
      try { out = await run(); } catch (e) { if (signal.aborted) throw e; out = await run(); }   // the first run after choosing a file sometimes fails once
      ok = true; stats = out.stats;
      axios.post(`${API_BASE}/api/jobs/${job.id}/device-log`, { ok: true, seconds: stats.seconds, speed: stats.speed, info: { cores: deviceCap?.cores, memory: deviceCap?.memory, fps: deviceCap?.fps, ua: deviceCap?.ua } }).catch(() => {});
      return URL.createObjectURL(out.blob);
    } catch (e) {
      if (cancelled.current) { const err = new Error('Cancelled'); err.cancelled = true; throw err; }
      error = String(e?.message || e).slice(0, 300);
    } finally {
      document.removeEventListener('visibilitychange', onHide);
      try { await lock?.release(); } catch (e) { /* ignore */ }
    }
    // fallback: the same video, rendered by the server (voice clips are cached, nothing is charged)
    axios.post(`${API_BASE}/api/jobs/${job.id}/device-log`, { ok: false, error, fell_back: true, seconds: (Date.now() - t0) / 1000, info: { cores: deviceCap?.cores, memory: deviceCap?.memory, fps: deviceCap?.fps, ua: deviceCap?.ua } }).catch(() => {});
    setProgress({ pct: 0, stage: tr('Your device could not make it, so the server is doing it') });
    const lines = (result.project?.segments || []).map((g) => ({ id: g.id, start: g.start, text: g.text, source_text: g.source_text || '', tempo: g.tempo || null, speaker: g.speaker || null }));
    const { data } = await axios.post(`${API_BASE}/api/jobs/${job.id}/rerender`, { segments: lines, device_render: false });
    await followJob(data.job_id);
    return null;
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
        ? (job.eta_seconds
          ? tr('Waiting in line: you are #{n}, about {m} min', { n: job.queue_position, m: Math.max(1, Math.ceil(job.eta_seconds / 60)) })
          : tr('Waiting in line: you are #{n}, starting soon', { n: job.queue_position }))
        : job.stage;
      setProgress({ pct: job.progress, stage: waiting });
    } while (job.status === 'running' || job.status === 'queued');

    if (job.status === 'cancelled') throw stopped();
    if (job.status === 'error') throw new Error(job.error);
    const result = job.result;
    if (result.expired) throw new Error(tr('This result has expired. Please generate it again.'));
    if (result.device_plan) {   // the server made the sound + a plan: this device draws the picture (any problem -> the server renders instead)
      const done = await finishOnDevice(job, result);
      if (!done) return;   // fell back: a new server job is being followed
      lastDevice.current = true;
      setResultVideoUrl(done); setResultDownloadUrl(done);
    } else {
      lastDevice.current = false;
      setResultVideoUrl(absUrl(result.video_url));
      setResultDownloadUrl(absUrl(result.download_url));
    }
    setSubtitleUrl(absUrl(result.subtitle_url));
    setTimeline(result.timeline.filter((scene) => scene.text));
    setProject(result.project || null);
    setBgKept(!!result.background_kept);
    setJobId(job.id);
    setNotes(
      [
        result.subtitles_detected ? tr('Source subtitles detected and blurred.') : tr('No source subtitles found, nothing blurred.'),
        keepBackground && outputKind === 'dub' && !result.background_kept ? tr('Background music separation failed; voice-only audio.') : '',
        ...(result.warnings || []).map(trs),
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
      const { data } = await axios.post(`${API_BASE}/api/jobs/${jobId}/rerender`, { segments: lines, speaker_voices: speakerVoices || undefined, ...finish, device_render: lastDevice.current && !!videoFile });
      setProgress({ pct: 0, stage: tr('Queued') });
      await followJob(data.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  // Open a finished video from "My videos": the same preview, download and editor as right after rendering.
  const openJob = async (id) => {
    try {
      const { data: job } = await axios.get(`${API_BASE}/api/jobs/${id}`);
      const result = job.result;
      if (result?.device_plan) { setErrorMessage(tr('This video was made on your device and is not stored on the server. Upload the video again to make it again.')); setView('create'); return; }
      if (!result || result.expired) { setErrorMessage(tr('This result has expired. Please generate it again.')); setView('create'); return; }
      setErrorMessage('');
      setResultVideoUrl(absUrl(result.video_url));
      setResultDownloadUrl(absUrl(result.download_url));
      setSubtitleUrl(absUrl(result.subtitle_url));
      setTimeline((result.timeline || []).filter((scene) => scene.text));
      setProject(result.project || null);
      setBgKept(!!result.background_kept);
      setJobId(job.id);
      setNotes((result.warnings || []).map(trs).join(' '));
      setView('create');
      window.scrollTo?.({ top: 0 });
    } catch (e) {
      setErrorMessage(trs(e.response?.data?.detail) || e.message);
      setView('create');
    }
  };

  if (!token) return <AuthScreen onAuth={onAuth} notice={notice} />;

  return (
    <Shell view={view} setView={setView} account={account} onLogout={() => logout()}>
      {showLibrary && (
        <VoiceLibrary voices={voices} looks={looks} selected={voiceType} playing={playing} onPlay={playSample}
          onSelect={(v) => { setVoiceType(v.name); setVoiceGender(v.gender); }} onClose={() => setShowLibrary(false)} apiBase={API_BASE} />
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

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">{tr('Video quality (size)')}</label>
            <Select value={resolution} onChange={setResolution} options={[
              { value: '720', label: tr('720p - faster (recommended)') },
              { value: '1080', label: tr('1080p - sharper, slower') }]} />
          </div>

          {deviceCap?.ok && (
            <div className={`rounded-xl border-2 p-3 transition-all duration-300 ease-out ${useDevice
              ? 'border-emerald-400 bg-emerald-500/15 shadow-[0_0_0_3px_rgba(52,211,153,0.15)]'
              : 'border-slate-700 bg-slate-800/60 hover:border-slate-500'}`}>
              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input type="checkbox" checked={useDevice} onChange={(e) => setUseDevice(e.target.checked)} className="peer sr-only" />
                <span aria-hidden="true" className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 transition-all duration-300 ease-out peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-300 ${useDevice
                  ? 'border-emerald-400 bg-emerald-500 scale-110'
                  : 'border-slate-500 bg-slate-900'}`}>
                  <svg viewBox="0 0 20 20" className={`h-4 w-4 text-white transition-all duration-300 ease-out ${useDevice ? 'opacity-100 scale-100' : 'opacity-0 scale-50'}`} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 10.5l4 4 8-9" />
                  </svg>
                </span>
                <span className={`text-sm transition-colors duration-300 ${useDevice ? 'text-emerald-100' : 'text-slate-200'}`}>
                  <span className="font-semibold">{tr('Render on my device (faster, beta)')}</span>
                  <span className={`block text-xs mt-0.5 transition-colors duration-300 ${useDevice ? 'text-emerald-200/80' : 'text-slate-400'}`}>{tr('Rendered with your phone\'s own processor. Keep the screen open.')}</span>
                </span>
              </label>
              {queue?.busy && !useDevice && (
                <div className="mt-2 text-xs text-amber-300">
                  {tr('The server is busy: about {m} min wait.', { m: Math.max(1, Math.ceil(queue.wait_seconds / 60)) })}{' '}
                  <button type="button" onClick={() => setUseDevice(true)} className="underline font-semibold">{tr('Use my phone instead (faster)')}</button>
                </div>
              )}
            </div>
          )}

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
                key={logoInputKey}
                type="file"
                accept="image/*"
                onChange={(e) => setCustomLogo(e.target.files[0] || null)}
                className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-sm file:font-semibold file:bg-slate-700 file:text-white hover:file:bg-slate-600 cursor-pointer"
              />
              {customLogo && (
                <button type="button" onClick={removeLogo} className="mt-2 px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-sm text-slate-200">
                  {tr('Remove logo')}
                </button>
              )}
            </div>
          </div>

          {sourceUrl && !loading && !resultVideoUrl && (
            <PreviewStudio src={sourceUrl} logoFile={customLogo} fx={previewFx} onChange={changePreviewFx} />
          )}

          {standardOk && (
            <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-2">
              <label className="block text-sm font-medium text-slate-300">{tr('Voice quality')}</label>
              <div className="grid gap-2 sm:grid-cols-2">
                {[['premium', 'High quality', '30 voices to choose from, with emotion. Uses more of your allowance.'],
                  ['standard', 'Standard', 'Two clear Burmese voices (female / male), no emotion. Cheaper and almost always available.']].map(([q, title, text]) => (
                  <button key={q} type="button" onClick={() => { setVoiceQuality(q); if (q === 'standard') { setVoiceType(voiceGender === 'male' ? 'Charon' : 'Kore'); } }}
                    className={`text-left rounded-xl border p-3 ${voiceQuality === q ? 'border-purple-500 bg-purple-950/40' : 'border-slate-700 bg-slate-800/50 hover:bg-slate-800'}`}>
                    <span className="block text-sm font-semibold">{tr(title)}</span>
                    <span className="block text-xs text-slate-400 mt-0.5">{tr(text)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {standard ? (
            <div className="rounded-xl border border-purple-500/30 bg-purple-950/30 p-4">
              <p className="text-sm text-purple-200 mb-3">{tr('The Standard voice reads everything in one clear Burmese voice. In a full movie, all female characters share the female voice and all male characters the male voice.')}</p>
              <div className="grid grid-cols-2 gap-2">
                {[['female', 'Nilar'], ['male', 'Thiha']].map(([g, name]) => (
                  <div key={g} className={`p-2 rounded-xl border ${voiceGender === g ? 'border-purple-500 bg-purple-950/40' : 'border-slate-800 bg-slate-800/50 hover:bg-slate-800'}`}>
                    <button type="button" onClick={() => { setVoiceGender(g); setVoiceType(g === 'male' ? 'Charon' : 'Kore'); }} className="w-full text-left">
                      <span className="font-semibold text-sm block">{name}</span>
                      <span className="text-xs text-purple-300 capitalize">{tr('{gender} Burmese voice', { gender: tr(g) })}</span>
                    </button>
                    <button type="button" onClick={() => playSample({ name: `azure-${g}`, sample_url: `/api/azure-samples/${g}.wav` })} className="mt-2 text-xs text-purple-300 hover:text-white">
                      {playing === `azure-${g}` ? tr('■ Stop') : tr('▶ Play')}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
          <div className="rounded-xl border border-purple-500/30 bg-purple-950/30 p-4">
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
                  <div className="flex items-center gap-3 mt-2 text-xs whitespace-nowrap">
                    <button type="button" onClick={() => playSample(v)} className="text-purple-300 hover:text-white whitespace-nowrap">
                      {playing === v.name ? tr('■ Stop') : tr('▶ Play')}
                    </button>
                    <a href={`${API_BASE}${v.sample_url}`} download title={tr('⬇ Download')} aria-label={tr('⬇ Download')} className="text-slate-400 hover:text-white">⬇</a>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" onClick={() => setShowLibrary(true)} className="mt-3 w-full px-3 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-sm text-purple-200 text-center leading-snug">
              {/* long text: the two halves wrap onto their own lines on a phone instead of running off the button */}
              <span className="flex flex-wrap justify-center items-center gap-x-2 gap-y-0.5">
                {tr('See more voices ({n}) · search & categories →', { n: voices.length + looks.length }).split(' · ').map((part, i) => (
                  <span key={i} className={`break-words min-w-0 ${i ? 'text-xs text-purple-300/80' : 'font-medium'}`}>{part}</span>
                ))}
              </span>
            </button>
          </div>
          )}

          {/* What kind of video is this? */}
          <div className="rounded-xl border border-slate-800 bg-slate-800/30 p-4 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[['recap', tr('Recap video'), tr('One narrator voice')], ['full', tr('Full movie / drama'), tr('A voice for each character')]].map(([k, title, sub]) => {
                const on = filmMode === k;
                return (
                  <button
                    key={k} type="button" onClick={() => setFilmMode(k)} aria-pressed={on}
                    className={`group flex sm:flex-col items-center sm:text-center gap-4 sm:gap-3 rounded-2xl px-4 py-5 sm:py-6 text-left border-2 transition-all duration-300 ease-out active:scale-[0.98] ${on
                      ? 'border-purple-400 bg-purple-600/25 shadow-[0_8px_30px_-8px_rgba(168,85,247,0.55)] sm:-translate-y-0.5'
                      : 'border-slate-700 bg-slate-800/50 hover:border-slate-500 hover:bg-slate-800'}`}
                  >
                    <span className={`shrink-0 transition-transform duration-300 ease-out ${on ? 'scale-110 -rotate-3' : 'group-hover:scale-105'}`}>
                      {k === 'recap' ? <RecapIcon /> : <MovieIcon />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-base font-bold text-white">{title}</span>
                      <span className={`block text-xs mt-0.5 transition-colors duration-300 ${on ? 'text-purple-200' : 'text-slate-400'}`}>{sub}</span>
                    </span>
                  </button>
                );
              })}
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
                {outputKind === 'dub' && (
                  <>
                    <label className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                      <span>{tr('Original music & sounds')}</span>
                      <Select size="sm" className="w-full sm:w-auto min-w-0 sm:max-w-md" value={bgMode} onChange={setBgMode} options={[
                        { value: 'separate', label: tr('Keep music & sound effects, remove the original speech (recommended)') },
                        { value: 'original', label: tr('Keep everything, lowered (original speech stays faintly audible)') },
                        { value: 'off', label: tr('Remove all original sound') }]} />
                    </label>
                    {!standard && (<label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={emotionOn} onChange={(e) => setEmotionOn(e.target.checked)} className="w-4 h-4 accent-purple-500" />
                      {tr('Add emotion to the voices (angry, sad, scared…; a few key lines)')}
                    </label>)}
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
                {tr('Tighten long translations to fit each scene')}
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
                <Editor key={jobId} project={project} videoRef={videoRef} busy={loading} voices={voices} looks={looks} playingVoice={playing} onPlaySample={playSample} onPreviewLine={previewLine} previewing={previewing} onApply={applyEdits} finish={finish} onFinish={(patch) => setFinish((f) => ({ ...f, ...patch }))} hasBackground={bgKept} />
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
      {view === 'history' && <HistoryPage apiBase={API_BASE} refreshKey={usageKey} onOpen={openJob} />}
      {view === 'topup' && <TopUpPage apiBase={API_BASE} onChanged={refreshAccount} />}
      {view === 'usage' && <UsageDashboard apiBase={API_BASE} refreshKey={usageKey} />}
    </Shell>
  );
}

export default App;
