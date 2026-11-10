import { useEffect, useRef, useState } from 'react';
import * as catalogApi from '../api/catalog.js';
import * as jobsApi from '../api/jobs.js';
import { API_BASE } from '../api/client.js';
import { useI18n } from '../i18n.jsx';

// Voice sample playback AND live line-preview playback share one audio element on purpose: starting either one must
// stop the other, so they cannot be split across two hooks without just passing the ref between them.
export default function useVoicePlayback(jobId) {
  const { trs } = useI18n();
  const [voices, setVoices] = useState([]);
  const [looks, setLooks] = useState([]);
  const [playing, setPlaying] = useState(null);     // voice name currently playing a SAMPLE
  const [previewing, setPreviewing] = useState(null); // line key currently previewing
  const audioRef = useRef(null);
  const previewBlobUrlRef = useRef('');   // the one in-flight preview-line blob: revoked before the next one and on unmount

  useEffect(() => {
    catalogApi.getVoices().then((r) => setVoices(r.data)).catch(() => setVoices([]));
    catalogApi.getLooks().then((r) => setLooks(r.data)).catch(() => setLooks([]));
    return () => {
      audioRef.current?.pause();
      if (previewBlobUrlRef.current) URL.revokeObjectURL(previewBlobUrlRef.current);
    };
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

  const previewLine = async (line, voiceName) => {
    if (!jobId) return;
    audioRef.current?.pause();
    setPreviewing(line.key);
    try {
      const { data } = await jobsApi.previewLine(jobId, { id: line.id ?? null, text: line.text, voice: voiceName });
      if (previewBlobUrlRef.current) URL.revokeObjectURL(previewBlobUrlRef.current);   // release the previous preview's blob before making a new one
      const url = URL.createObjectURL(data);
      previewBlobUrlRef.current = url;
      const audio = new Audio(url);
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

  return { voices, looks, playing, previewing, playSample, previewLine };
}
