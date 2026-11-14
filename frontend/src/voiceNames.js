// Burmese DISPLAY names for the 30 Gemini voices (owner, 2026-11-14: "Zephyr, Kore..." mean nothing to our users).
// Display only: the real voice name (the key) is what the server, stored projects, sample files and the clip cache use.
// Nilar / Thiha are NOT used here: they are the two Standard (Azure) voices. [Burmese script, Latin spelling]
export const VOICE_NAMES = {
  // female
  Zephyr: ['နှင်း', 'Hnin'], Kore: ['သီရိ', 'Thiri'], Leda: ['မေ', 'May'], Aoede: ['စု', 'Su'], Callirrhoe: ['ခင်', 'Khin'],
  Autonoe: ['အိ', 'Ei'], Despina: ['သူဇာ', 'Thuzar'], Erinome: ['နန္ဒာ', 'Nandar'], Laomedeia: ['ဖြူ', 'Phyu'], Achernar: ['ချို', 'Cho'],
  Gacrux: ['ရတနာ', 'Yadanar'], Pulcherrima: ['ဇင်', 'Zin'], Vindemiatrix: ['ဝေ', 'Wai'], Sulafat: ['မြတ်', 'Myat'],
  // male
  Puck: ['ထက်', 'Htet'], Charon: ['အောင်', 'Aung'], Fenrir: ['ရဲ', 'Ye'], Orus: ['ဇော်', 'Zaw'], Enceladus: ['ကျော်', 'Kyaw'],
  Iapetus: ['မင်း', 'Min'], Umbriel: ['နိုင်', 'Naing'], Algieba: ['သူရ', 'Thura'], Algenib: ['ဘိုး', 'Bo'], Rasalgethi: ['ထွန်း', 'Tun'],
  Alnilam: ['မျိုး', 'Myo'], Schedar: ['ဝင်း', 'Win'], Achird: ['စိုး', 'Soe'], Zubenelgenubi: ['လင်း', 'Lin'], Sadachbia: ['ဟိန်း', 'Hein'],
  Sadaltager: ['ပိုင်', 'Paing'],
};

// What to show for a voice: the Burmese name in the app's language (script for Myanmar, Latin spelling for English).
// Unknown names (looks, Azure voices, future voices) are returned unchanged.
export const voiceLabel = (name, lang = 'my') => (VOICE_NAMES[name] ? VOICE_NAMES[name][lang === 'en' ? 1 : 0] : name);
// Text a search should match: both spellings plus the original name.
export const voiceSearch = (name) => (VOICE_NAMES[name] ? `${VOICE_NAMES[name].join(' ')} ${name}` : name);
