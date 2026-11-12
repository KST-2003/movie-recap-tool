// Subtitle style shared by the editor (live sample) and the on-device render. The font files in /fonts are the SAME files the server
// draws with (backend/fonts, SIL OFL), so a style looks the same wherever the video is made. Keep in step with recap_engine.CAPTION_FONTS.
export const CAPTION_FONTS = [
  { id: 'sans', label: 'Noto Sans (bold)', file: 'NotoSansMyanmar-Bold.ttf', family: 'RecapCaptionSans' },
  { id: 'sans-regular', label: 'Noto Sans (regular)', file: 'NotoSansMyanmar-Regular.ttf', family: 'RecapCaptionSansRegular' },
  { id: 'serif', label: 'Noto Serif (bold)', file: 'NotoSerifMyanmar-Bold.ttf', family: 'RecapCaptionSerif' },
  { id: 'padauk', label: 'Padauk (bold)', file: 'Padauk-Bold.ttf', family: 'RecapCaptionPadauk' },
];
export const DEFAULT_CAPTION_STYLE = { font: 'sans', size: 1.0, color: '#FFEB3B', outline: '#000000', bg: '#000000', bg_opacity: 0.59, position: 'auto' };
export const CAPTION_PRESETS = [
  { label: 'Yellow on dark', style: { color: '#FFEB3B', outline: '#000000', bg: '#000000', bg_opacity: 0.59 } },
  { label: 'White on dark', style: { color: '#FFFFFF', outline: '#000000', bg: '#000000', bg_opacity: 0.59 } },
  { label: 'White, outline only', style: { color: '#FFFFFF', outline: '#000000', bg: '#000000', bg_opacity: 0 } },
  { label: 'Black on white', style: { color: '#111111', outline: '', bg: '#FFFFFF', bg_opacity: 0.9 } },
];

const SYSTEM = '"Noto Sans Myanmar", "Myanmar Sangam MN", "Myanmar Text", Padauk, sans-serif';
const loading = {};

/** Loads one style font (once) and returns the CSS font-family list to draw with; the system Burmese fonts stay as the fallback. */
export function loadCaptionFont(id) {
  const font = CAPTION_FONTS.find((f) => f.id === id) || CAPTION_FONTS[0];
  if (!loading[font.id]) {
    loading[font.id] = (async () => {
      try {
        const face = new FontFace(font.family, `url(${import.meta.env.BASE_URL}fonts/${font.file})`);
        await face.load();
        document.fonts.add(face);
        return `"${font.family}", ${SYSTEM}`;
      } catch (e) {
        loading[font.id] = null;   // try again next time
        return SYSTEM;
      }
    })();
  }
  return loading[font.id];
}

export const rgba = (hex, alpha) => {
  const n = parseInt((hex || '#000000').slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
};
