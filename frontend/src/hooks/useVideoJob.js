import { useEffect, useRef, useState } from 'react';
import * as jobsApi from '../api/jobs.js';
import { absUrl } from '../api/client.js';
import { useI18n } from '../i18n.jsx';

// One video, one job, one result: the actual state machine behind "pick a file -> upload -> poll -> show the result
// -> maybe re-render from the editor." This is the biggest of the four hooks and genuinely can't be split much
// further without just passing state between smaller pieces -- it's one cohesive lifecycle, not a grab-bag.
//
// `settings` is the object returned by useRenderSettings(): this hook reads it to build the upload/rerender bodies
// but does not own or change it. `onSettled()` is called once after a new-video job finishes (success, error, or
// cancel) -- the caller uses it to refresh the account's remaining minutes and bump the usage-page refresh key.
export default function useVideoJob(settings, onSettled) {
  const { tr, trs } = useI18n();
  const { voiceType, finish, allowVoiceSpeedup, videoSpeed, brightness, contrast, saturation, logoPosition, logoSize,
    logoXY, blurBoxes, aspect, fitMode, pan, fitTranslation, keepBackground, filmMode, outputKind, bgMode, emotionOn,
    softMusic } = settings;

  const [videoFile, setVideoFile] = useState(null);
  const [customLogo, setCustomLogo] = useState(null);
  const [sourceUrl, setSourceUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [resultVideoUrl, setResultVideoUrl] = useState('');
  const [resultDownloadUrl, setResultDownloadUrl] = useState('');
  const [subtitleUrl, setSubtitleUrl] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [notes, setNotes] = useState('');
  const [timeline, setTimeline] = useState([]);
  const [project, setProject] = useState(null); // editable lines of the finished job
  const [jobId, setJobId] = useState('');
  const [bgKept, setBgKept] = useState(false);   // the result has the film's own music/effects under the voice
  const [upload, setUpload] = useState(null); // % uploaded while the video is being sent
  const [elapsed, setElapsed] = useState(0);
  const [progress, setProgress] = useState({ pct: 0, stage: '' });
  const videoRef = useRef(null);
  const activeJob = useRef('');
  const cancelled = useRef(false);

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

  const cancelJob = async () => {
    cancelled.current = true;
    if (activeJob.current) {
      try { await jobsApi.cancelJob(activeJob.current); } catch (e) { /* the loop below stops anyway */ }
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

  // Poll a job until it finishes, then show its result (used for new videos and for editor re-renders).
  const followJob = async (id) => {
    let job;
    activeJob.current = id;
    const stopped = () => Object.assign(new Error('Cancelled'), { cancelled: true });
    if (cancelled.current) { await cancelJob(); throw stopped(); } // Cancel was pressed while the job was being created
    do {
      await new Promise((resolve) => setTimeout(resolve, 1500));
      if (cancelled.current) throw stopped();
      ({ data: job } = await jobsApi.getJob(id));
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
    setResultVideoUrl(absUrl(result.video_url));
    setResultDownloadUrl(absUrl(result.download_url));
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
      const { data: started } = await jobsApi.createJob(formData, (e) => e.total && setUpload(Math.round((100 * e.loaded) / e.total)));
      setUpload(null);
      setProgress({ pct: 0, stage: tr('Queued') });
      await followJob(started.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
      setUpload(null);
      onSettled?.();
    }
  };

  const applyEdits = async (lines, speakerVoices) => {
    cancelled.current = false;
    activeJob.current = '';
    setLoading(true);
    setErrorMessage('');
    setNotes('');
    try {
      const { data } = await jobsApi.rerender(jobId, { segments: lines, speaker_voices: speakerVoices || undefined, ...finish });
      setProgress({ pct: 0, stage: tr('Queued') });
      await followJob(data.job_id);
    } catch (error) {
      showError(error);
    } finally {
      setLoading(false);
    }
  };

  return {
    videoFile, setVideoFile, customLogo, setCustomLogo, sourceUrl,
    loading, resultVideoUrl, resultDownloadUrl, subtitleUrl, errorMessage, notes, timeline, project, jobId, bgKept,
    upload, elapsed, progress, videoRef,
    handleGenerateRecap, cancelJob, applyEdits,
  };
}
