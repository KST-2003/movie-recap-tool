import { useState } from 'react';

// Every setting the upload form and the live preview (PreviewStudio) read or write. Pure UI/form state: no network
// calls, nothing here depends on a job existing yet. `previewFx`/`changePreviewFx` is the shape PreviewStudio expects.
export default function useRenderSettings() {
  const [voiceType, setVoiceType] = useState('Kore');
  const [voiceGender, setVoiceGender] = useState('female');
  // Finishing settings: not in the form any more, edited in the editor AFTER the first result (they re-render the video).
  const [finish, setFinish] = useState({ blur_subtitles: true, enable_subtitles: true, remove_watermark: false, enable_flip: false, bg_volume: null });
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
  const [aspect, setAspect] = useState('original'); // output format, chosen BEFORE uploading (like CapCut)
  const [fitMode, setFitMode] = useState('blur');     // 'blur' = whole picture over a blurred copy | 'crop' = fill the frame
  const [pan, setPan] = useState({ x: 0.5, y: 0.5 });  // crop mode: which part of the picture stays
  const previewFx = { videoSpeed, brightness, contrast, saturation, logoSize, logoPosition, logoXY, blurBoxes, flip: false,
    aspect, fitMode, panX: pan.x, panY: pan.y };
  const changePreviewFx = (patch) => {
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

  return {
    voiceType, setVoiceType, voiceGender, setVoiceGender,
    finish, setFinish,
    allowVoiceSpeedup, setAllowVoiceSpeedup,
    videoSpeed, setVideoSpeed, brightness, setBrightness, contrast, setContrast, saturation, setSaturation,
    logoPosition, setLogoPosition, logoSize, setLogoSize, logoXY, setLogoXY,
    blurBoxes, setBlurBoxes,
    aspect, setAspect, fitMode, setFitMode, pan, setPan,
    previewFx, changePreviewFx,
    fitTranslation, setFitTranslation, keepBackground, setKeepBackground,
    filmMode, setFilmMode, outputKind, setOutputKind, bgMode, setBgMode, emotionOn, setEmotionOn, softMusic, setSoftMusic,
  };
}
