"""Offline transcribe (faster-whisper) + translate (NLLB-200). No API keys, no quotas."""
import os
import subprocess
import tempfile
from safe_media import SAFE_IN
import sandbox

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
NLLB_MODEL = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")

# Whisper language code -> NLLB code
NLLB_CODES = {
    "my": "mya_Mymr", "en": "eng_Latn", "th": "tha_Thai", "zh": "zho_Hans",
    "ja": "jpn_Jpan", "ko": "kor_Hang", "vi": "vie_Latn", "id": "ind_Latn",
}

_whisper = None
_nllb = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def _get_nllb():
    global _nllb
    if _nllb is None:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(NLLB_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(NLLB_MODEL)
        model.eval()
        _nllb = (tok, model)
    return _nllb


def _translate(texts: list[str], src: str, tgt: str) -> list[str]:
    import torch
    tok, model = _get_nllb()
    tok.src_lang = NLLB_CODES.get(src, "eng_Latn")
    out = []
    for i in range(0, len(texts), 8):
        batch = tok(texts[i:i + 8], return_tensors="pt", padding=True, truncation=True, max_length=256)
        with torch.no_grad():
            ids = model.generate(
                **batch,
                forced_bos_token_id=tok.convert_tokens_to_ids(NLLB_CODES[tgt]),
                max_new_tokens=256,
                num_beams=4,
            )
        out += tok.batch_decode(ids, skip_special_tokens=True)
    return out


def dub(video_path: str, target_language: str) -> tuple[str | None, list[dict]]:
    if target_language not in NLLB_CODES:
        raise RuntimeError(f"Local translation does not support target language '{target_language}'.")
    with tempfile.TemporaryDirectory() as tmp:
        wav = os.path.join(tmp, "audio.wav")
        sandbox.run(
            ["ffmpeg", "-y", *SAFE_IN, "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", wav],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=300,
        )
        segs, info = _get_whisper().transcribe(wav, vad_filter=True, beam_size=5)
        raw = [(float(s.start), float(s.end), s.text.strip()) for s in segs if s.text.strip() and s.end > s.start]
    if not raw:
        raise RuntimeError("Whisper found no speech in the video.")
    source = info.language
    if source == target_language:
        translated = [t for _, _, t in raw]
    else:
        if source not in NLLB_CODES:
            raise RuntimeError(f"Local translation does not support source language '{source}'.")
        translated = _translate([t for _, _, t in raw], source, target_language)
    segments = [
        {"start": a, "end": b, "source_text": src, "translated_text": tr.strip()}
        for (a, b, src), tr in zip(raw, translated) if tr.strip()
    ]
    if not segments:
        raise RuntimeError("Local translation produced no text.")
    return source, segments
