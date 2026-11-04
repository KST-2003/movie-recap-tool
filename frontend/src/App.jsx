import React, { useEffect, useRef, useState } from 'react';
import axios from 'axios';

function App() {
  // Form State
  const [videoFile, setVideoFile] = useState(null);
  const [customLogo, setCustomLogo] = useState(null);
  const API_BASE = 'http://localhost:8000';
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
  const [fitTranslation, setFitTranslation] = useState(false);
  const [keepBackground, setKeepBackground] = useState(false);
  const [progress, setProgress] = useState({ pct: 0, stage: '' });
  const [notes, setNotes] = useState('');
  const [subtitleUrl, setSubtitleUrl] = useState('');
  const [timeline, setTimeline] = useState([]);

  // UI Processing & Result State
  const [loading, setLoading] = useState(false);
  const [resultVideoUrl, setResultVideoUrl] = useState('');
  const [resultDownloadUrl, setResultDownloadUrl] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  // Handle Form Submission
  const handleGenerateRecap = async (e) => {
    e.preventDefault();
    if (!videoFile) {
      alert('ကျေးဇူးပြု၍ ဗီဒီယိုဖိုင် ရွေးချယ်ပေးပါ (Please select a video file)');
      return;
    }

    setLoading(true);
    setErrorMessage('');
    setResultVideoUrl('');
    setTimeline([]);

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

    try {
      // Start a background job on the local FastAPI backend, then poll its progress.
      const baseUrl = API_BASE;
      const { data: started } = await axios.post(`${baseUrl}/api/jobs`, formData);
      setProgress({ pct: 0, stage: 'Queued' });

      let job;
      do {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        ({ data: job } = await axios.get(`${baseUrl}/api/jobs/${started.job_id}`));
        setProgress({ pct: job.progress, stage: job.stage });
      } while (job.status === 'running');

      if (job.status === 'error') throw new Error(job.error);

      const result = job.result;
      setResultVideoUrl(baseUrl + result.video_url);
      setResultDownloadUrl(baseUrl + result.download_url);
      setSubtitleUrl(baseUrl + result.subtitle_url);
      setTimeline(result.timeline.filter((scene) => scene.text));
      setNotes(
        [
          result.subtitles_detected ? 'Source subtitles detected and blurred.' : 'No source subtitles found, nothing blurred.',
          keepBackground && !result.background_kept ? 'Background music separation failed; voice-only audio.' : '',
        ].filter(Boolean).join(' ')
      );
    } catch (error) {
      console.error('Processing error:', error);
      setErrorMessage(error.response?.data?.detail || error.message || 'ဗီဒီယို ထုတ်လုပ်ရာတွင် အမှားအယွင်း ရှိသွားပါသည်');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-6 font-sans">
      <div className="max-w-3xl mx-auto bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl">
        
        {/* Header */}
        <h1 className="text-2xl font-bold mb-6 text-purple-400 flex items-center gap-2">
          🎬 RedNote Recap Studio (မြန်မာ)
        </h1>

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
                Tighten long translations to fit each scene (needs ANTHROPIC_API_KEY on the backend)
              </span>
            </label>
            <label className="flex items-center space-x-3 cursor-pointer">
              <input
                type="checkbox"
                checked={keepBackground}
                onChange={(e) => setKeepBackground(e.target.checked)}
                className="w-4 h-4 accent-purple-500"
              />
              <span className="text-sm text-slate-300">Keep original background music and effects (slower)</span>
            </label>
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
            <div className="flex justify-between text-xs text-slate-400 mb-1">
              <span>{progress.stage}</span>
              <span>{progress.pct}%</span>
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
        {resultVideoUrl && (
          <div className="mt-8 border-t border-slate-800 pt-6">
            <h2 className="text-lg font-semibold text-slate-200 mb-4">
              ၄။ ဗီဒီယို ကြည့်ရှုရန် နှင့် ဒေါင်းလုပ်လုပ်ရန် (Preview & Download)
            </h2>
            <div className="flex flex-col items-center space-y-4">
              <video
                src={resultVideoUrl}
                controls
                className="w-full max-w-xs rounded-xl border border-slate-800 shadow-lg"
              />
              <a
                href={resultDownloadUrl}
                download
                className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-semibold rounded-xl text-sm transition-all shadow-md"
              >
                📥 ဗီဒီယို သိမ်းဆည်းမည် (Download MP4)
              </a>
              <a
                href={subtitleUrl}
                download
                className="px-6 py-2.5 bg-slate-700 hover:bg-slate-600 text-white font-semibold rounded-xl text-sm transition-all"
              >
                Download subtitles (.srt)
              </a>
              {notes && <p className="text-xs text-slate-400">{notes}</p>}
              {timeline.length > 0 && (
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
