import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';
import Editor from './Editor.jsx';
import Mascot from './Mascot.jsx';
import Splash from './Splash.jsx';
import VoiceLibrary from './VoiceLibrary.jsx';
import Select from './Select.jsx';
import { voiceLabel } from './voiceNames.js';
import PreviewStudio, { ASPECTS } from './PreviewStudio.jsx';
import CaptionStyleControls from './CaptionStyleControls.jsx';
import { DEFAULT_CAPTION_STYLE } from './captionFonts.js';
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

const STEP_NAMES = ['Video', 'Look', 'Voice', 'Finish'];   // phone steps of the Create form

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

  const input = 'w-full rounded-2xl bg-page border border-violet-100 px-4 py-3 text-sm text-ink placeholder:text-ink-faint outline-none transition-shadow focus:border-violet-400 focus:shadow-[0_0_0_4px_rgba(139,92,246,0.15)]';
  return (
    <div className="relative min-h-screen overflow-hidden text-ink p-6 font-sans flex items-center justify-center">
      {/* soft clouds drifting behind the card */}
      <div aria-hidden="true" className="pointer-events-none absolute -top-24 -left-20 h-72 w-72 rounded-full bg-lavender/50 blur-3xl animate-drift" />
      <div aria-hidden="true" className="pointer-events-none absolute -bottom-24 -right-16 h-80 w-80 rounded-full bg-blush/50 blur-3xl animate-drift [animation-delay:-4s]" />
      <div aria-hidden="true" className="pointer-events-none absolute top-1/4 right-1/4 h-40 w-40 rounded-full bg-popcorn/40 blur-3xl animate-drift [animation-delay:-2s]" />
      <div className="absolute right-4 top-4"><LangSwitch /></div>
      <form onSubmit={submit} className="relative w-full max-w-sm rounded-[2rem] bg-white/90 backdrop-blur border border-white p-7 pt-16 shadow-card space-y-4 animate-rise">
        <div className="absolute -top-14 left-1/2 -translate-x-1/2 rounded-full bg-white p-2 shadow-card"><Mascot className="h-24 w-24" /></div>
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight whitespace-nowrap"><span className="bg-gradient-to-r from-violet-600 to-pink-500 bg-clip-text text-transparent">Recat</span> <span className="text-amber-500">Studio</span></h1>
          <p className="mt-1 text-sm text-ink-soft">{tr('Burmese recaps, purr-fectly made.')}</p>
        </div>
        {notice && !error && <p className="rounded-2xl bg-amber-50 px-3 py-2 text-sm text-amber-700">{trs(notice)}</p>}
        <input className={input} type="text" autoComplete="username" autoCapitalize="none" spellCheck={false} placeholder={tr('Username')} value={username} onChange={(e) => setUsername(e.target.value)} required />
        <input className={input} type="password" autoComplete="current-password" placeholder={tr('Password')} value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="rounded-2xl bg-rose-50 px-3 py-2 text-sm text-rose-600 animate-pop">{error}</p>}
        <button disabled={busy} className="btn-candy animate-shimmer w-full py-3 rounded-2xl font-semibold text-white shadow-pop hover:-translate-y-0.5 disabled:opacity-50">{busy ? '…' : tr('Log in')}</button>
        <p className="text-center text-xs text-ink-faint">{tr('Your username and password are given to you by the admin.')}</p>
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
    <div className="w-full max-w-xs mt-3 rounded-2xl border border-violet-100 bg-white/60 p-3 text-xs">
      <div className="flex justify-between text-ink-soft mb-2">
        <span>{tr('Working on your video')}</span>
        <span className="font-mono">{mmss(elapsed)}</span>
      </div>
      {!uploading && progress.eta != null && (
        <div className="mb-2 text-violet-600">
          {progress.over ? tr('Almost done: this one is taking a little longer than usual')
            : progress.eta < 60 ? tr('Less than a minute left')
              : tr('About {m} min left', { m: Math.ceil(progress.eta / 60) })}
        </div>
      )}
      <ol className="space-y-1.5">
        {STEPS.map((st, i) => (subsOnly && i >= 3 && i <= 5 ? null : (st && { st, i }))).filter(Boolean).map(({ st, i }) => {
          const done = i === 0 ? !uploading : pct >= st.to;
          const active = !done && (i === 0 ? uploading : pct >= st.from && pct < st.to);
          return (
            <li key={st.label} className="flex items-start gap-2">
              <span className={`mt-0.5 w-4 h-4 flex-shrink-0 rounded-full flex items-center justify-center text-[10px] ${
                done ? 'bg-emerald-500 text-white animate-pop' : active ? 'border-2 border-violet-400 border-t-transparent animate-spin' : 'border border-violet-300'
              }`}>{done ? '✓' : ''}</span>
              <span className={done ? 'text-ink-soft' : active ? 'text-ink' : 'text-ink-faint'}>
                {tr(st.label)}
                {active && <span className="block text-violet-600">{i === 0 ? `${upload}%` : trs(progress.stage)}</span>}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2 text-[11px] text-ink-faint">{tr('Longer videos can take a few minutes. You can cancel at any time.')}</p>
    </div>
  );
}

function App() {
  const { tr, trs, lang } = useI18n();
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
  const [splash, setSplash] = useState(() => !!localStorage.getItem('token'));   // opening animation (~2 s) for a signed-in user, and after signing in
  const onAuth = (data) => {
    setSplash(true);
    localStorage.setItem('token', data.token);
    axios.defaults.headers.common.Authorization = `Bearer ${data.token}`;
    setNotice('');
    setToken(data.token);
    setAccount(data);
  };
  const refreshAccount = () => axios.get(`${API_BASE}/api/auth/me`).then((r) => { setAccount(r.data); setBlockedUntil(r.data.upload_blocked_seconds > 0 ? Date.now() + r.data.upload_blocked_seconds * 1000 : 0); }).catch(() => {});
  const [blockedUntil, setBlockedUntil] = useState(0);   // paused after repeated failed/cancelled videos
  const [nowTick, setNowTick] = useState(Date.now());
  useEffect(() => { if (!blockedUntil) return undefined; const id = setInterval(() => setNowTick(Date.now()), 30000); return () => clearInterval(id); }, [blockedUntil]);
  const blockedSeconds = Math.max(0, Math.round((blockedUntil - nowTick) / 1000));
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
  // Video from a RedNote / YouTube / TikTok link instead of a file: the server fetches it, this page downloads that copy for the preview and
  // the on-device render, and "Generate" sends link_id instead of uploading the file again.
  const [linkText, setLinkText] = useState('');
  const [linkBusy, setLinkBusy] = useState('');     // '' | status text while fetching
  const [linkInfo, setLinkInfo] = useState(null);   // { id, title, file }
  const fetchLink = async () => {
    if (!linkText.trim() || linkBusy) return;
    setErrorMessage('');
    setLinkBusy(tr('Getting the video… (a long video can take a minute)'));
    try {
      const { data } = await axios.post(`${API_BASE}/api/link/fetch`, { url: linkText.trim() });
      const res = await axios.get(`${API_BASE}/api/link/${data.id}/file`, {
        responseType: 'blob',
        onDownloadProgress: (e) => setLinkBusy(`${tr('Loading the video')} ${Math.round((100 * e.loaded) / (e.total || data.size || 1))}%`),
      });
      const name = `${(data.title || 'video').replace(/[\\/:*?"<>|]/g, ' ').slice(0, 60)}.mp4`;
      const file = new File([res.data], name, { type: 'video/mp4' });
      setLinkInfo({ id: data.id, title: data.title || '', site: data.site || 'RedNote', file });
      setVideoFile(file);
      setLinkText('');
    } catch (error) {
      const detail = error.response?.data?.detail;
      setErrorMessage(typeof detail === 'string' && [400, 404, 429, 503].includes(error.response?.status) ? trs(detail)
        : tr('The video could not be fetched from this link. Please upload the video file instead.'));
    } finally {
      setLinkBusy('');
    }
  };
  const [customLogo, setCustomLogo] = useState(null);
  const [logoInputKey, setLogoInputKey] = useState(0); // changing it empties the file input (a chosen file cannot be cleared otherwise)
  const [voiceType, setVoiceType] = useState('Kore');
  const [voices, setVoices] = useState([]);
  const [looks, setLooks] = useState([]);
  const [showLibrary, setShowLibrary] = useState(false);
  const [voiceGender, setVoiceGender] = useState('female');
  const [voiceQuality, setVoiceQuality] = useState('standard'); // default Standard when the server offers it (owner's rule 2026-11-13; without Azure `standard` below is false = High quality). 'premium' = Gemini (30 voices, emotion) | 'standard' = Azure (2 voices, cheaper, more usage)
  const [standardOk, setStandardOk] = useState(false);
  const [separationOk, setSeparationOk] = useState(true);   // can the server remove the original speech (Demucs)? the small server cannot
  const standard = voiceQuality === 'standard' && standardOk;
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  useEffect(() => {
    axios.get(`${API_BASE}/api/voices`).then((r) => setVoices(r.data)).catch(() => setVoices([]));
    axios.get(`${API_BASE}/api/looks`).then((r) => setLooks(r.data)).catch(() => setLooks([]));
    axios.get(`${API_BASE}/api/voice-quality`).then((r) => { setStandardOk(!!r.data.standard); setSeparationOk(r.data.separation !== false); if (r.data.separation === false) setBgMode((m) => (m === 'separate' ? 'original' : m)); }).catch(() => setStandardOk(false));
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
  const [logoOnTop, setLogoOnTop] = useState(false);   // layer order: logo over the subtitle (default: subtitle over the logo)
  const [captionStyle, setCaptionStyle] = useState({ ...DEFAULT_CAPTION_STYLE });   // subtitle look chosen BEFORE generating
  const [deviceCap, setDeviceCap] = useState(null);     // can this phone/browser draw the video itself? (WebCodecs + WebGL + speed test)
  const [useDevice, setUseDevice] = useState(true);      // on by default; only shown / sent when this device passes the capability test. "Render on my device (faster, beta)"
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
  const previewFx = { videoSpeed, brightness, contrast, saturation, logoSize, logoPosition, logoXY, blurBoxes, logoOnTop, flip: false,
    aspect, fitMode, panX: pan.x, panY: pan.y };
  const removeLogo = () => { setCustomLogo(null); setLogoXY(null); setLogoInputKey((k) => k + 1); };
  const changePreviewFx = (patch) => {
    if (patch.removeLogo) { removeLogo(); return; }
    const set = { videoSpeed: setVideoSpeed, brightness: setBrightness, contrast: setContrast, saturation: setSaturation,
      logoSize: setLogoSize, logoPosition: setLogoPosition, logoXY: setLogoXY, blurBoxes: setBlurBoxes, logoOnTop: setLogoOnTop, captionStyle: setCaptionStyle };
    if ('panX' in patch) setPan((p) => ({ ...p, x: patch.panX }));
    if ('panY' in patch) setPan((p) => ({ ...p, y: patch.panY }));
    Object.entries(patch).forEach(([k, v]) => set[k]?.(v));
  };
  const [fitTranslation, setFitTranslation] = useState(true);
  const [keepBackground, setKeepBackground] = useState(false);
  const [filmMode, setFilmMode] = useState('recap'); // 'recap' = one narrator voice | 'full' = characters with their own voices
  const setOutputKind = (kind) => { setOutputKindRaw(kind); setFinish((f) => ({ ...f, enable_subtitles: kind !== 'voice' })); };
  const [outputKind, setOutputKindRaw] = useState('dub'); // 'voice' = Burmese voice-over WITHOUT our subtitles (sent as output=dub + enable_subtitles=false) | 'dub' = Burmese voice-over | 'subtitles' = keep original sound, subtitles only
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

  // Drag a video file from the computer and drop it anywhere on the Create page (same as choosing it with the button).
  const videoInputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  useEffect(() => {
    if (!token || view !== 'create') return undefined;
    const hasFiles = (e) => Array.from(e.dataTransfer?.types || []).includes('Files');
    const onFileInput = (e) => e.target?.tagName === 'INPUT' && e.target.type === 'file';   // the browser handles those itself
    let depth = 0;
    const enter = (e) => { if (!hasFiles(e)) return; depth += 1; setDragOver(true); };
    const leave = (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) setDragOver(false); };
    const over = (e) => {
      if (!hasFiles(e) || onFileInput(e)) return;
      e.preventDefault();                       // without this the browser opens the file instead of giving it to us
      e.dataTransfer.dropEffect = loading ? 'none' : 'copy';
    };
    const drop = (e) => {
      if (!hasFiles(e)) return;
      depth = 0; setDragOver(false);
      if (onFileInput(e)) return;
      e.preventDefault();
      if (loading) return;
      const file = Array.from(e.dataTransfer.files || []).find((f) => f.type.startsWith('video/') || /\.(mp4|mov|m4v|mkv|webm|avi|flv|wmv|ts|3gp)$/i.test(f.name));
      if (!file) { setErrorMessage(tr('That is not a video file. Please drop a video.')); return; }
      setErrorMessage('');
      setVideoFile(file);
      try {                                     // show the dropped file's name in the "Upload video" field too
        const dt = new DataTransfer(); dt.items.add(file);
        if (videoInputRef.current) videoInputRef.current.files = dt.files;
      } catch { /* older browsers: the preview still shows the video */ }
    };
    window.addEventListener('dragenter', enter); window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', over); window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter); window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', over); window.removeEventListener('drop', drop);
      setDragOver(false);
    };
  }, [token, view, loading]);

  // Phones: the Create form is shown one step at a time (the user can go back / forward or tap a step at any time; nothing is
  // unmounted, hidden steps keep their values). Wide screens (lg+) show the whole form and ignore `step`.
  const [step, setStep] = useState(1);
  const formRef = useRef(null);
  const stepCls = (n) => (step === n ? 'contents' : 'max-lg:hidden lg:contents');
  const goStep = (n) => {
    setStep(Math.min(STEP_NAMES.length, Math.max(1, n)));
    if (window.matchMedia?.('(max-width: 1023px)').matches) requestAnimationFrame(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  // Handle Form Submission
  const handleGenerateRecap = async (e) => {
    e.preventDefault();
    if (!videoFile) {
      setStep(1);
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
    if (linkInfo && linkInfo.file === videoFile) {   // fetched from a link: the server already has it
      formData.append('link_id', linkInfo.id);
      formData.append('link_title', linkInfo.title);
    } else {
      formData.append('video_file', videoFile);
    }
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
    formData.append('logo_above_subtitle', logoOnTop ? 'true' : 'false');
    if (customLogo && logoXY) {
      formData.append('logo_x', logoXY[0]);
      formData.append('logo_y', logoXY[1]);
    }
    // Boxes are in the output frame as shown (the render applies them after reframe and flip).
    formData.append('manual_blurs', JSON.stringify(blurBoxes.map((b) => [b.x, b.y, b.w, b.h])));
    if (JSON.stringify(captionStyle) !== JSON.stringify(DEFAULT_CAPTION_STYLE)) formData.append('caption_style', JSON.stringify(captionStyle));
    formData.append('resolution', resolution);
    formData.append('device_render', !!(useDevice && deviceCap?.ok));
    formData.append('aspect', aspect);
    formData.append('fit_mode', fitMode);
    formData.append('pan_x', pan.x);
    formData.append('pan_y', pan.y);
    formData.append('fit_translation', fitTranslation);
    formData.append('keep_background', keepBackground);
    formData.append('mode', filmMode);
    formData.append('output', outputKind === 'subtitles' ? 'subtitles' : 'dub');
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
    // Users get calm notices, never raw errors: texts written for users (limits, busy, paused) come through; anything else (network, 500, code errors) is a generic notice. The admin sees the real error in the job log.
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    const userText = typeof detail === 'string' && [400, 402, 413, 429, 503].includes(status) ? detail : (!error.response && error.message && /busy|refunded|minutes/i.test(error.message) ? error.message : '');
    setErrorMessage(userText ? trs(userText) : tr('We could not complete this just now. Our team has been notified. Please try again a little later.'));
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
      setProgress({ pct: job.progress, stage: waiting, eta: job.status === 'running' && Number.isFinite(job.eta_seconds) ? job.eta_seconds : null, over: !!job.eta_over });
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
        keepBackground && outputKind !== 'subtitles' && !result.background_kept ? tr('Background music separation failed; voice-only audio.') : '',
        ...(result.warnings || []).map(trs),
      ].filter(Boolean).join(' ')
    );
  };

  const applyEdits = async (lines, speakerVoices, blurWindows, captionStyle) => {
    cancelled.current = false;
    activeJob.current = '';
    setLoading(true);
    setErrorMessage('');
    setNotes('');
    try {
      const { data } = await axios.post(`${API_BASE}/api/jobs/${jobId}/rerender`, { segments: lines, speaker_voices: speakerVoices || undefined, blur_windows: blurWindows || undefined, caption_style: captionStyle || undefined, ...finish, device_render: lastDevice.current && !!videoFile });
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
      setErrorMessage(tr('We could not complete this just now. Our team has been notified. Please try again a little later.'));
      setView('create');
    }
  };

  if (!token) return <AuthScreen onAuth={onAuth} notice={notice} />;

  return (
    <Shell view={view} setView={setView} account={account} onLogout={() => logout()}>
      {splash && <Splash onDone={() => setSplash(false)} />}
      {dragOver && view === 'create' && (
        <div className="fixed inset-0 z-50 pointer-events-none flex items-center justify-center bg-ink/80 p-6 text-white">
          <div className="rounded-3xl border-4 border-dashed border-violet-400 bg-violet-500/10 px-8 py-10 text-center">
            <div className="text-4xl mb-3" aria-hidden="true">🎬</div>
            <p className="text-lg font-semibold text-ink">{loading ? tr('A video is being made. Please wait until it is finished.') : tr('Drop the video here')}</p>
          </div>
        </div>
      )}
      {showLibrary && (
        <VoiceLibrary voices={voices} looks={looks} selected={voiceType} playing={playing} onPlay={playSample}
          onSelect={(v) => { setVoiceType(v.name); setVoiceGender(v.gender); }} onClose={() => setShowLibrary(false)} apiBase={API_BASE} />
      )}
      <div className={view === 'create' ? '' : 'hidden'}>
      {/* hero banner */}
      <div className={`relative max-w-3xl mx-auto mb-5 overflow-hidden rounded-[2rem] bg-gradient-to-br from-violet-500 via-purple-400 to-pink-300 p-6 pr-32 sm:pr-44 text-white shadow-pop animate-rise ${step > 1 ? 'max-lg:hidden' : ''}`}>
        <div aria-hidden="true" className="pointer-events-none absolute -right-10 -top-16 h-56 w-56 rounded-full border border-white/20" />
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-28 h-80 w-80 rounded-full border border-white/15" />
        <div aria-hidden="true" className="pointer-events-none absolute left-1/3 -bottom-8 h-20 w-40 rounded-full bg-white/15 blur-xl animate-drift" />
        <span className="inline-block rounded-full bg-white/90 px-3 py-1 text-xs font-semibold text-violet-600">Recat Studio</span>
        <h1 className="mt-3 text-2xl sm:text-3xl font-bold leading-tight">{tr('What are we recapping today?')}</h1>
        <p className="mt-1 text-sm text-white/85">{tr('Drop in a video and Recat turns it into Burmese.')}</p>
        <Mascot className="absolute right-3 sm:right-8 bottom-1 h-28 w-28 sm:h-36 sm:w-36 drop-shadow-xl" />
      </div>
      <div className="max-w-3xl mx-auto bg-white border border-white rounded-[2rem] p-5 sm:p-7 shadow-card animate-rise [animation-delay:80ms]">

        {blockedSeconds > 0 && (
          <div role="alert" className="mb-5 rounded-2xl border-2 border-amber-400/70 bg-amber-500/10 p-4 flex gap-3 animate-[selectIn_200ms_ease-out]">
            <span className="text-2xl leading-none" aria-hidden="true">⚠️</span>
            <div className="min-w-0 text-sm text-amber-700 space-y-1">
              <p className="font-semibold">{tr('Your uploads are paused for now')}</p>
              <p>{tr('Your last 5 videos did not finish (failed or cancelled), so new videos are paused to keep the service stable. Please try again in about {t}. Our admin has been notified, and your minutes were refunded.', { t: blockedSeconds >= 3600 ? tr('{h} h {m} min', { h: Math.floor(blockedSeconds / 3600), m: Math.ceil((blockedSeconds % 3600) / 60) }) : tr('{m} min', { m: Math.max(1, Math.ceil(blockedSeconds / 60)) }) })}</p>
            </div>
          </div>
        )}
        <form ref={formRef} onSubmit={handleGenerateRecap} className="flex flex-col gap-6 scroll-mt-20">
          {/* Phones: the form is split into 4 steps (one on screen at a time, free to jump); wide screens show everything */}
          <ol className="lg:hidden flex items-center gap-1.5" aria-label={tr('Steps')}>
            {STEP_NAMES.map((name, i) => {
              const n = i + 1; const on = step === n; const done = n < step;
              return (
                <li key={name} className={on ? 'flex-[2.2] min-w-0' : 'flex-1 min-w-0'}>
                  <button type="button" onClick={() => goStep(n)} aria-current={on ? 'step' : undefined}
                    className={`w-full flex items-center justify-center gap-1.5 rounded-full px-2 py-2 text-xs font-semibold transition-all duration-300 ${on ? 'bg-violet-500 text-white shadow-pop' : done ? 'bg-violet-100 text-violet-600' : 'bg-page text-ink-faint border border-violet-100'}`}>
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] ${on ? 'bg-white/25' : done ? 'bg-violet-500 text-white' : 'bg-violet-100 text-ink-soft'}`}>{done ? '✓' : n}</span>
                    {on && <span className="truncate">{tr(name)}</span>}
                  </button>
                </li>
              );
            })}
          </ol>
          
          <div className={stepCls(1)}>
          {/* Format first, then the video (like CapCut) */}
          <div className="rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-3">
            <label className="block text-sm font-medium text-ink-soft">{tr('Video format')}</label>
            <div className="flex flex-wrap gap-2">
              {[['original', tr('Original')], ['9:16', '9:16'], ['1:1', '1:1'], ['4:5', '4:5'], ['16:9', '16:9']].map(([k, label]) => {
                const [w, h] = ASPECTS[k] || [3, 4];
                const s = 26 / Math.max(w, h);
                return (
                  <button
                    key={k} type="button" onClick={() => setAspect(k)}
                    className={`flex items-center gap-2 px-3 py-2 rounded-2xl text-sm border ${aspect === k ? 'border-violet-400 bg-violet-500/30 text-ink' : 'border-violet-200 bg-violet-50/50 text-ink-soft'}`}
                  >
                    <span className={`inline-block border-2 rounded-sm ${aspect === k ? 'border-violet-300' : 'border-violet-300'}`} style={{ width: ASPECTS[k] ? w * s : 20, height: ASPECTS[k] ? h * s : 20, borderStyle: ASPECTS[k] ? 'solid' : 'dashed' }} />
                    {label}
                  </button>
                );
              })}
            </div>
            {aspect !== 'original' && (
              <div className="flex gap-4 text-sm text-ink-soft flex-wrap">
                {[['blur', tr('Fit (blurred background)')], ['crop', tr('Fill (crop)')]].map(([k, label]) => (
                  <label key={k} className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="fitMode" checked={fitMode === k} onChange={() => setFitMode(k)} className="accent-violet-500" />
                    {label}
                  </label>
                ))}
              </div>
            )}
            {!sourceUrl && (
              <div className="flex justify-center">
                <div
                  style={{ aspectRatio: ASPECTS[aspect] ? ASPECTS[aspect].join(' / ') : '16 / 9', width: ASPECTS[aspect] && ASPECTS[aspect][1] > ASPECTS[aspect][0] ? 'min(100%, 12rem)' : 'min(100%, 20rem)' }}
                  className="rounded-2xl border border-dashed border-violet-300 flex items-center justify-center text-xs text-ink-faint text-center p-2"
                >
                  {tr('Choose a video to see it in this frame')}
                </div>
              </div>
            )}
          </div>
          </div>

          <div className={stepCls(4)}>
          <div>
            <label className="block text-sm font-medium text-ink-soft mb-2">{tr('Video quality (size)')}</label>
            <Select value={resolution} onChange={setResolution} options={[
              { value: '720', label: tr('720p - faster (recommended)') },
              { value: '1080', label: tr('1080p - sharper, slower') }]} />
          </div>

          {deviceCap?.ok && (
            <div className={`rounded-2xl border-2 p-3 transition-all duration-300 ease-out ${useDevice
              ? 'border-emerald-400 bg-emerald-500/15 shadow-[0_0_0_3px_rgba(52,211,153,0.15)]'
              : 'border-violet-200 bg-violet-50/60 hover:border-violet-300'}`}>
              <label className="flex items-start gap-3 cursor-pointer select-none">
                <input type="checkbox" checked={useDevice} onChange={(e) => setUseDevice(e.target.checked)} className="peer sr-only" />
                <span aria-hidden="true" className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border-2 transition-all duration-300 ease-out peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-300 ${useDevice
                  ? 'border-emerald-400 bg-emerald-500 scale-110 text-white'
                  : 'border-violet-300 bg-white'}`}>
                  <svg viewBox="0 0 20 20" className={`h-4 w-4 text-ink transition-all duration-300 ease-out ${useDevice ? 'opacity-100 scale-100' : 'opacity-0 scale-50'}`} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M4 10.5l4 4 8-9" />
                  </svg>
                </span>
                <span className={`text-sm transition-colors duration-300 ${useDevice ? 'text-emerald-700' : 'text-ink'}`}>
                  <span className="font-semibold">{tr('Render on my device (faster, beta)')}</span>
                  <span className={`block text-xs mt-0.5 transition-colors duration-300 ${useDevice ? 'text-emerald-700/80' : 'text-ink-soft'}`}>{tr('Rendered with your phone\'s own processor. Keep the screen open.')}</span>
                </span>
              </label>
              {queue?.busy && !useDevice && (
                <div className="mt-2 text-xs text-amber-700">
                  {tr('The server is busy: about {m} min wait.', { m: Math.max(1, Math.ceil(queue.wait_seconds / 60)) })}{' '}
                  <button type="button" onClick={() => setUseDevice(true)} className="underline font-semibold">{tr('Use my phone instead (faster)')}</button>
                </div>
              )}
            </div>
          )}
          </div>

          <div className={stepCls(1)}>
          {/* File Upload Section */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-ink-soft mb-2">
                {tr('Upload video')}
              </label>
              <input
                ref={videoInputRef}
                type="file"
                accept="video/*"
                onChange={(e) => setVideoFile(e.target.files[0])}
                className="w-full text-sm text-ink-soft file:mr-4 file:py-2 file:px-4 file:rounded-2xl file:border-0 file:text-sm file:font-semibold file:bg-violet-500 file:text-white hover:file:bg-violet-500 cursor-pointer"
              />
              <p className="hidden md:block mt-1 text-xs text-ink-faint">{tr('You can also drag a video file and drop it anywhere on this page.')}</p>
              <div className="mt-3">
                <label className="block text-xs text-ink-soft mb-1">{tr('Or paste a RedNote, YouTube or TikTok link')}</label>
                <div className="flex gap-2">
                  <input type="text" inputMode="url" value={linkText} onChange={(e) => setLinkText(e.target.value)} disabled={!!linkBusy || loading}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); fetchLink(); } }}
                    placeholder="https://…"
                    className="min-w-0 flex-1 rounded-2xl bg-violet-50 border border-violet-200 px-3 py-2 text-sm text-ink outline-none focus:border-violet-400" />
                  <button type="button" onClick={fetchLink} disabled={!linkText.trim() || !!linkBusy || loading}
                    className="shrink-0 px-3 py-2 rounded-2xl bg-violet-500 text-white text-sm font-semibold disabled:opacity-40">{tr('Get video')}</button>
                </div>
                {linkBusy && <p className="mt-1 text-xs text-violet-600">{linkBusy}</p>}
                {!linkBusy && linkInfo && linkInfo.file === videoFile && (
                  <p className="mt-1 text-xs text-emerald-700 break-words">{tr('From {site}: {title}', { site: linkInfo.site, title: linkInfo.title || tr('video') })}</p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-ink-soft mb-2">
                {tr('Logo (optional)')}
              </label>
              <input
                key={logoInputKey}
                type="file"
                accept="image/*"
                onChange={(e) => setCustomLogo(e.target.files[0] || null)}
                className="w-full text-sm text-ink-soft file:mr-4 file:py-2 file:px-4 file:rounded-2xl file:border-0 file:text-sm file:font-semibold file:bg-violet-100 file:text-ink hover:file:bg-violet-200 cursor-pointer"
              />
              {customLogo && (
                <button type="button" onClick={removeLogo} className="mt-2 px-3 py-1.5 rounded-lg bg-violet-100 hover:bg-violet-200 text-sm text-ink">
                  {tr('Remove logo')}
                </button>
              )}
            </div>
          </div>
          </div>

          <div className={stepCls(2)}>
          {sourceUrl && !loading && !resultVideoUrl && (
            <>
              <PreviewStudio src={sourceUrl} logoFile={customLogo} fx={{ ...previewFx, captionStyle: outputKind === 'voice' ? null : captionStyle }} onChange={changePreviewFx} />
              {outputKind !== 'voice' && <CaptionStyleControls cap={captionStyle} onChange={setCaptionStyle} showSample={false} />}
              {outputKind !== 'voice' && <p className="text-xs text-ink-faint -mt-2">{tr('The sample line in the preview shows the subtitle style. Drag it up or down to place it. "Automatic" puts subtitles over the original ones when they are found.')}</p>}
            </>
          )}
          {!(sourceUrl && !loading && !resultVideoUrl) && (
            <p className="lg:hidden rounded-2xl border border-dashed border-violet-200 bg-page p-6 text-center text-sm text-ink-soft">
              {!sourceUrl ? tr('Choose a video in step 1 first. Then you can set the look here.') : tr('The look is set while the video is being made. Change it in the editor below the result.')}
            </p>
          )}
          </div>

          <div className={stepCls(3)}>
          {standardOk && (
            <div className="rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-2">
              <label className="block text-sm font-medium text-ink-soft">{tr('Voice quality')}</label>
              <div className="grid gap-2 sm:grid-cols-2">
                {[['standard', 'Standard', 'Two clear Burmese voices (female / male), no emotion. Cheaper and almost always available.'],
                  ['premium', 'High quality', '30 voices to choose from, with emotion. Uses more of your allowance.']].map(([q, title, text]) => (
                  <button key={q} type="button" onClick={() => { setVoiceQuality(q); if (q === 'standard') { setVoiceType(voiceGender === 'male' ? 'Charon' : 'Kore'); } }}
                    aria-pressed={voiceQuality === q}
                    className={`relative text-left rounded-2xl border-2 p-3 pr-11 transition-all duration-300 ${voiceQuality === q
                      ? 'border-violet-500 bg-gradient-to-br from-violet-500 to-violet-400 text-white shadow-pop sm:-translate-y-0.5'
                      : 'border-violet-100 bg-white text-ink opacity-80 hover:opacity-100 hover:border-violet-300'}`}>
                    {/* the chosen card is filled and ticked; the other one is plain white with an empty circle */}
                    <span aria-hidden="true" className={`absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full border-2 ${voiceQuality === q ? 'border-white bg-white text-violet-600' : 'border-violet-200 bg-white text-transparent'}`}>
                      <svg key={String(voiceQuality === q)} viewBox="0 0 20 20" className={`h-3.5 w-3.5 ${voiceQuality === q ? 'animate-pop' : ''}`} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M4 10.5l4 4 8-9" /></svg>
                    </span>
                    <span className="block text-sm font-semibold">{tr(title)}</span>
                    <span className={`block text-xs mt-0.5 ${voiceQuality === q ? 'text-white/90' : 'text-ink-soft'}`}>{tr(text)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {standard ? (
            <div className="rounded-2xl border border-violet-400/30 bg-violet-100/30 p-4">
              <p className="text-sm text-violet-600 mb-3">{tr('The Standard voice reads everything in one clear Burmese voice. In a full movie, all female characters share the female voice and all male characters the male voice.')}</p>
              <div className="grid grid-cols-2 gap-2">
                {[['female', 'Nilar'], ['male', 'Thiha']].map(([g, name]) => (
                  <div key={g} className={`p-2 rounded-2xl border ${voiceGender === g ? 'border-violet-400 bg-violet-100/40' : 'border-violet-100 bg-violet-50/50 hover:bg-violet-50'}`}>
                    <button type="button" onClick={() => { setVoiceGender(g); setVoiceType(g === 'male' ? 'Charon' : 'Kore'); }} className="w-full text-left">
                      <span className="font-semibold text-sm block">{name}</span>
                      <span className="text-xs text-violet-600 capitalize">{tr('{gender} Burmese voice', { gender: tr(g) })}</span>
                    </button>
                    <button type="button" onClick={() => playSample({ name: `azure-${g}`, sample_url: `/api/azure-samples/${g}.wav` })} className="mt-2 text-xs text-violet-600 hover:text-ink">
                      {playing === `azure-${g}` ? tr('■ Stop') : tr('▶ Play')}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
          <div className="rounded-2xl border border-violet-400/30 bg-violet-100/30 p-4">
            <div className="flex gap-2 mb-3">
              {['female', 'male'].map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setVoiceGender(g)}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold capitalize ${
                    voiceGender === g ? 'bg-violet-500 text-white' : 'bg-violet-50 text-ink-soft hover:bg-violet-100'
                  }`}
                >
                  {tr(g)}
                </button>
              ))}
            </div>
            {voices.length === 0 && (
              <p className="text-xs text-ink-soft">{tr('No voice samples available: the default voice will be used.')}</p>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {[...voices.filter((v) => v.gender === voiceGender).slice(0, 4), ...voices.filter((v) => v.gender === voiceGender).slice(4).filter((v) => v.name === voiceType)].map((v) => (
                <div
                  key={v.name}
                  className={`p-2 rounded-2xl border transition-all ${
                    voiceType === v.name
                      ? 'border-violet-500 bg-violet-100 ring-2 ring-violet-400 shadow-pop'
                      : 'border-violet-100 bg-white hover:bg-violet-50'
                  }`}
                >
                  <button type="button" onClick={() => setVoiceType(v.name)} className="w-full text-left">
                    <span className="font-semibold text-sm block">{voiceLabel(v.name, lang)}</span>
                    <span className="text-xs text-violet-600 capitalize">{tr('{gender} Burmese voice', { gender: tr(v.gender) })}</span>
                  </button>
                  <div className="flex items-center gap-3 mt-2 text-xs whitespace-nowrap">
                    <button type="button" onClick={() => playSample(v)} className="text-violet-600 hover:text-ink whitespace-nowrap">
                      {playing === v.name ? tr('■ Stop') : tr('▶ Play')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" onClick={() => setShowLibrary(true)} className="mt-3 w-full px-3 py-2.5 rounded-2xl bg-violet-50 hover:bg-violet-100 text-sm text-violet-600 text-center leading-snug">
              {/* long text: the two halves wrap onto their own lines on a phone instead of running off the button */}
              <span className="flex flex-wrap justify-center items-center gap-x-2 gap-y-0.5">
                {tr('See more voices ({n}) · search & categories →', { n: voices.length + looks.length }).split(' · ').map((part, i) => (
                  <span key={i} className={`break-words min-w-0 ${i ? 'text-xs text-violet-600/80' : 'font-medium'}`}>{part}</span>
                ))}
              </span>
            </button>
          </div>
          )}

          {/* What kind of video is this? */}
          <div className="rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[['recap', tr('Recap video'), tr('One narrator voice')], ['full', tr('Full movie / drama'), tr('A voice for each character')]].map(([k, title, sub]) => {
                const on = filmMode === k;
                return (
                  <button
                    key={k} type="button" onClick={() => setFilmMode(k)} aria-pressed={on}
                    className={`group flex sm:flex-col items-center sm:text-center gap-4 sm:gap-3 rounded-2xl px-4 py-5 sm:py-6 text-left border-2 transition-all duration-300 ease-out active:scale-[0.98] ${on
                      ? 'border-violet-400 bg-violet-500/25 shadow-[0_8px_30px_-8px_rgba(139,92,246,0.45)] sm:-translate-y-0.5'
                      : 'border-violet-200 bg-violet-50/50 hover:border-violet-300 hover:bg-violet-50'}`}
                  >
                    <span className={`shrink-0 transition-transform duration-300 ease-out ${on ? 'scale-110 -rotate-3' : 'group-hover:scale-105'}`}>
                      {k === 'recap' ? <RecapIcon /> : <MovieIcon />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-base font-bold text-ink">{title}</span>
                      <span className={`block text-xs mt-0.5 transition-colors duration-300 ${on ? 'text-violet-600' : 'text-ink-soft'}`}>{sub}</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="text-sm text-ink-soft">
                <div className="flex gap-4 flex-wrap">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'dub'} onChange={() => setOutputKind('dub')} className="accent-violet-500" />
                    {tr('Burmese voice-over + subtitles')}
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'voice'} onChange={() => setOutputKind('voice')} className="accent-violet-500" />
                    {tr('Burmese voice-over only (no subtitles)')}
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="outputKind" checked={outputKind === 'subtitles'} onChange={() => setOutputKind('subtitles')} className="accent-violet-500" />
                    {tr('Burmese subtitles only (original sound stays)')}
                  </label>
                </div>
            </div>
            {filmMode === 'full' && (
              <div className="space-y-3 text-sm text-ink-soft">
                {outputKind !== 'subtitles' && (
                  <>
                    <label className="flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-2">
                      <span>{tr('Original music & sounds')}</span>
                      <Select size="sm" className="w-full sm:w-auto min-w-0 sm:max-w-md" value={bgMode} onChange={setBgMode} options={[
                        ...(separationOk ? [{ value: 'separate', label: tr('Keep music & sound effects, remove the original speech (recommended)') }] : []),
                        { value: 'original', label: tr(separationOk ? 'Keep everything, lowered (original speech stays faintly audible)' : 'Keep everything, original sound quiet under the Burmese voice (recommended)') },
                        { value: 'off', label: tr('Remove all original sound') }]} />
                    </label>
                    {!standard && (<label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={emotionOn} onChange={(e) => setEmotionOn(e.target.checked)} className="w-4 h-4 accent-violet-500" />
                      {tr('Add emotion to the voices (angry, sad, scared…; a few key lines)')}
                    </label>)}
                  </>
                )}
              </div>
            )}
            <label className="flex items-center gap-2 cursor-pointer text-sm text-ink-soft">
              <input type="checkbox" checked={softMusic} onChange={(e) => setSoftMusic(e.target.checked)} className="w-4 h-4 accent-violet-500" />
              {tr('Add a soft background tone (optional)')}
            </label>
          </div>
          </div>

          <div className={stepCls(4)}>
          {/* Sync policy + editing tools */}
          <div className="rounded-2xl border border-violet-100 bg-violet-50/30 p-4 space-y-4">
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={fitTranslation}
                onChange={(e) => setFitTranslation(e.target.checked)}
                className="w-4 h-4 accent-violet-500"
              />
              <span className="text-sm text-ink-soft">
                {tr('Tighten long translations to fit each scene')}
              </span>
            </label>
            {filmMode === 'recap' && outputKind !== 'subtitles' && <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={keepBackground}
                onChange={(e) => setKeepBackground(e.target.checked)}
                className="w-4 h-4 accent-violet-500"
              />
              <span className="text-sm text-ink-soft">{tr('Keep original background music and effects (slower)')}</span>
            </label>}
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={allowVoiceSpeedup}
                onChange={(e) => setAllowVoiceSpeedup(e.target.checked)}
                className="w-4 h-4 accent-violet-500"
              />
              <span className="text-sm text-ink-soft">
                {tr('Allow slight voice speed-up (up to 1.35x) before slowing the video')}
              </span>
            </label>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading || blockedSeconds > 0}
            className="btn-candy animate-shimmer w-full py-4 font-bold rounded-2xl shadow-pop hover:-translate-y-0.5 disabled:opacity-50 cursor-pointer text-white"
          >
            {loading ? tr('⚡ Processing…') : tr('✨ Generate video')}
          </button>
          </div>
          <div className="lg:hidden flex items-center gap-3">
            {step > 1 && <button type="button" onClick={() => goStep(step - 1)} className="flex-1 rounded-2xl border border-violet-200 bg-white py-3 text-sm font-semibold text-ink-soft">← {tr('Back')}</button>}
            {step < STEP_NAMES.length && <button type="button" onClick={() => goStep(step + 1)} className="flex-[2] rounded-2xl bg-violet-500 py-3 text-sm font-semibold text-white shadow-pop">{tr('Next')} →</button>}
          </div>
        </form>

        {loading && (
          <div className="mt-4">
            <div className="flex justify-between items-center text-xs text-ink-soft mb-1">
              <span>{trs(progress.stage)}</span>
              <span className="flex items-center gap-3">
                {progress.pct}%
                <button type="button" onClick={cancelJob} className="px-2 py-0.5 rounded bg-violet-100 hover:bg-rose-200 text-ink">{tr('Cancel')}</button>
              </span>
            </div>
            <div className="h-2 bg-violet-50 rounded-full overflow-hidden">
              <div className="h-full bg-violet-500 transition-all text-white" style={{ width: `${progress.pct}%` }} />
            </div>
          </div>
        )}

        {/* Error Message */}
        {errorMessage && (
          <div className="mt-4 p-4 bg-amber-500/10 border border-amber-400/60 text-amber-700 rounded-2xl text-sm flex gap-2">
            <span aria-hidden="true">ℹ️</span><span>{errorMessage}</span>
          </div>
        )}

        {/* Preview & Download Section */}
        {(resultVideoUrl || (loading && sourceUrl)) && (
          <div className="mt-8 border-t border-violet-100 pt-6">
            <h2 className="text-lg font-semibold text-ink mb-4">
              {tr('Preview & download')}
            </h2>
            <div className="flex flex-col items-center space-y-4">
              <div className="relative w-full max-w-xs min-h-[16rem]">
                <video
                  ref={videoRef}
                  src={resultVideoUrl || sourceUrl}
                  controls={!loading}
                  className="w-full rounded-2xl border border-violet-100 shadow-lg"
                />
                {loading && (
                  <div className="absolute inset-0 rounded-2xl bg-white/80 backdrop-blur-sm flex flex-col items-center justify-center gap-3 p-4 text-center text-ink">
                    <Mascot className="h-24 w-24 shrink-0" />
                    <p className="text-sm font-medium text-ink">{upload !== null && upload < 100 ? tr('Uploading {n}%', { n: upload }) : trs(progress.stage) || tr('Working…')}</p>
                    <div className="w-40 h-2 shrink-0 bg-violet-100 rounded-full overflow-hidden">
                      <div className="h-full rounded-full btn-candy animate-shimmer transition-all duration-700" style={{ width: `${upload !== null && upload < 100 ? upload : progress.pct}%` }} />
                    </div>
                    <button type="button" onClick={cancelJob} className="mt-1 px-4 py-1.5 shrink-0 rounded-full bg-white border border-violet-200 hover:bg-rose-100 hover:border-rose-200 text-sm font-medium">
                      {tr('Cancel')}
                    </button>
                  </div>
                )}
              </div>
              {loading && <ProcessingPanel upload={upload} progress={progress} elapsed={elapsed} subsOnly={(project ? project.output : outputKind) === 'subtitles'} />}
              {resultVideoUrl && <a
                href={resultDownloadUrl}
                download
                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-2xl text-sm transition-all shadow-md"
              >
                {tr('📥 Download video (MP4)')}
              </a>}
              {resultVideoUrl && <a
                href={subtitleUrl}
                download
                className="px-6 py-2.5 bg-violet-100 hover:bg-violet-200 text-ink font-semibold rounded-2xl text-sm transition-all"
              >
                {tr('Download subtitles (.srt)')}
              </a>}
              {notes && <p className="text-xs text-ink-soft">{notes}</p>}
              {project && (
                <Editor key={jobId} project={project} videoRef={videoRef} busy={loading} voices={voices} looks={looks} playingVoice={playing} onPlaySample={playSample} onPreviewLine={previewLine} previewing={previewing} onApply={applyEdits} finish={finish} onFinish={(patch) => setFinish((f) => ({ ...f, ...patch }))} hasBackground={bgKept} />
              )}
              {!project && timeline.length > 0 && (
                <ul className="w-full text-xs text-ink-soft space-y-1">
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
