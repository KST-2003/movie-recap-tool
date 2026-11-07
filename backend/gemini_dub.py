"""Gemini-based transcribe + translate. Long audio is cut at silences and processed in parallel."""
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

from gemini_tts import get_text_client as _get_client

MODEL = os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash")
CHUNK_SECONDS = float(os.getenv("GEMINI_DUB_CHUNK_SECONDS", "75"))
THINKING_BUDGET = int(os.getenv("GEMINI_THINKING_BUDGET", "0"))  # 0 = no hidden reasoning: several times faster
WORKERS = int(os.getenv("GEMINI_DUB_WORKERS", "6"))
LANGUAGE_NAMES = {"my": "Burmese (Myanmar)", "en": "English", "th": "Thai", "zh": "Chinese"}

SCHEMA = {
    "type": "object",
    "properties": {
        "source_language": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "source_text": {"type": "string"},
                    "translated_text": {"type": "string"},
                },
                "required": ["start", "end", "source_text", "translated_text"],
            },
        },
    },
    "required": ["segments"],
}


def _run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=timeout)


def _duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return float(out.stdout.strip())


def _silence_midpoints(path: str) -> list[float]:
    proc = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "silencedetect=noise=-30dB:d=0.2", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300,
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return [(a + b) / 2 for a, b in zip(starts, ends)]


def _plan_chunks(path: str, total: float) -> list[tuple[float, float]]:
    """Cut points at silences near every CHUNK_SECONDS so no sentence is split in half."""
    if total <= CHUNK_SECONDS * 1.3:
        return [(0.0, total)]
    silences = _silence_midpoints(path)
    cuts, cur = [], 0.0
    while total - cur > CHUNK_SECONDS * 1.3:
        target = cur + CHUNK_SECONDS
        window = [s for s in silences if cur + CHUNK_SECONDS * 0.6 <= s <= cur + CHUNK_SECONDS * 1.4]
        cur = min(window, key=lambda s: abs(s - target)) if window else target
        cuts.append(cur)
    bounds = [0.0] + cuts + [total]
    return list(zip(bounds[:-1], bounds[1:]))


EMOTIONS = {  # emotion tag from the transcript -> how the TTS is asked to speak ("Say <adverb>: ...")
    "neutral": None, "happy": "cheerfully", "sad": "sadly", "angry": "angrily", "fearful": "fearfully",
    "surprised": "with surprise", "excited": "excitedly", "tender": "softly and warmly", "whisper": "in a whisper",
}
SCHEMA_FULL = json.loads(json.dumps(SCHEMA))
_props = SCHEMA_FULL["properties"]["segments"]["items"]["properties"]
_props.update({
    "speaker": {"type": "string"},      # S1, S2 ... the same person keeps the same label inside this audio
    "gender": {"type": "string", "enum": ["male", "female", "unknown"]},
    "age": {"type": "string", "enum": ["child", "young", "adult", "elderly"]},
    "voice": {"type": "string"},        # 3-6 words on how this voice sounds (deep, raspy, bright ...): used to match speakers across parts
    "emotion": {"type": "string", "enum": list(EMOTIONS)},
})
SCHEMA_FULL["properties"]["segments"]["items"]["required"] += ["speaker", "gender", "emotion"]

CPS = float(os.getenv("BURMESE_CPS", "10"))  # Burmese characters a TTS voice reads per second (calibrate with real clips)
MAX_CUT_HINTS = 120
# Tone for the Burmese narration. Override with DUB_STYLE_NOTE in .env to tune it without touching code.
DEFAULT_STYLE = (
    "Write like a popular Myanmar movie-recap storyteller: spoken, colloquial Burmese (sentence endings like "
    "တယ် / ပါတယ်, not literary သည် / ၏), warm, vivid and gripping, as if telling the story to a friend. "
    "Use natural connecting words (then, but, suddenly, because of that) so the lines flow into each other."
)
STYLE_NOTE = os.getenv("DUB_STYLE_NOTE", DEFAULT_STYLE)


FULL_TONE = (
    "Translate for a Burmese audience that will HEAR this as a dubbed film: natural, neutral, everyday spoken Burmese "
    "that a real person would say in exactly this situation, with the right politeness level for who is talking to whom "
    "(keep each pair of characters consistent in how they address each other). Translate the MEANING and the intent, "
    "never word by word: no stiff literal phrases, no calques of foreign idioms, slang, insults or metaphors. Ask yourself: "
    "'how would a native Burmese speaker say this in this scene?' and write that. Examples of what NOT to do: rendering "
    "'it is miserable / I am struggling' as a bare literal word like ဆင်းရဲတယ်, rendering 'these people' as a cold label "
    "like ဒီလူတွေ, or rendering 'struggling like a dog' word for word as ခွေးလိုရုန်းရ - nobody talks like that. Say what is "
    "meant in plain natural Burmese instead. Keep strong language realistic but not crude. Each character speaks in the "
    "first person, as themselves (there is no narrator)."
)


def _cut_hint(cuts):
    if not cuts:
        return ""
    shown = ", ".join(f"{c:.1f}" for c in cuts[:MAX_CUT_HINTS])
    return f"\nSCENE CUTS in the picture, at these seconds from the start of this audio: {shown}."


def _prompt_full(target: str, cuts: list[float] | None = None) -> str:
    return (
        "This audio is from a film or series with several characters speaking. Transcribe all spoken dialogue into "
        "segments with precise start/end times in seconds from the start of this audio, then translate each segment "
        "into " + target + " for a dubbed voice-over. Skip music, sound effects and silence. Segments must not overlap "
        "and must be in chronological order. Also report the source language as an ISO code.\n"
        "SPEAKERS: give every segment a speaker label (S1, S2, ...): the same person always keeps the same label inside "
        "this audio and different people get different labels, even when they sound alike. Also give the speaker's "
        "gender, age group, a 3-6 word description of how their voice sounds (e.g. 'deep gruff older man', 'bright "
        "young woman'), and the emotion of that line (neutral, happy, sad, angry, fearful, surprised, excited, tender, "
        "whisper). Use neutral unless the emotion is clearly audible.\n"
        "MEANING FIRST: keep every fact, name, number and intention; never invent, skip or soften meaning. Names stay "
        "consistent. Each translated_text is a complete sentence (or clause) that makes sense in the conversation. Never "
        "cut a sentence in the middle; split overly long sentences at natural pauses.\n"
        f"TRANSLATION STYLE: {FULL_TONE}\n"
        "LENGTH: the line is spoken inside its own time slot (end - start). Match the source speech length: about "
        f"{CPS:g} characters per second of slot, at most {CPS * 1.3:g}; shorter wording is fine, dropping meaning is not.\n"
        "PUNCTUATION: a period (။) after every sentence and commas at natural breath points (the voice pauses on them)."
        + _cut_hint(cuts)
    )


def _prompt(target: str, cuts: list[float] | None = None, mode: str = "recap") -> str:
    if mode == "full":
        return _prompt_full(target, cuts)
    text = (
        "This audio is the narration of a fast-cut recap video (the picture changes every 1-3 seconds). "
        "Transcribe all spoken dialogue into segments with precise start/end times in seconds from the start of "
        "this audio, then translate each segment into " + target + " for a voice-over. Skip music and silence. "
        "Segments must not overlap and must be in chronological order. Also report the source language as an ISO code.\n"
        "MEANING FIRST: translate what is actually said. Keep every key fact, action, name, number and cause/effect; "
        "never invent, skip or change the meaning, and do not soften or exaggerate it. Names must stay consistent "
        "across all segments. Each translated_text must be a complete, grammatical sentence (or clause) that makes "
        "sense on its own and also reads naturally after the previous line. Never cut a sentence in the middle.\n"
        f"TONE: {STYLE_NOTE}\n"
        "LENGTH: every line is read aloud inside its own time slot (end - start) and should FILL it: not much "
        "shorter (no dead air where the source speaker was talking) and not longer. If the source speech is dense "
        "and continuous, the translation must be just as dense; leave silence only where the source really has "
        f"a pause. Aim for about {CPS:g} characters per second of slot and stay under {CPS * 1.3:g}. To save length, choose shorter "
        "wording and drop filler or repeated words, but do NOT drop information and do NOT turn the sentence into "
        "clipped, robotic fragments. If a source sentence is too long for its slot, split it into two segments at a "
        "natural pause instead of cutting its meaning.\n"
        "BOUNDARIES: end a segment at a natural pause or sentence end, preferring a moment that coincides with a "
        "scene cut. Never merge several sentences into one long segment.\n"
        "PUNCTUATION: use proper punctuation: a period (။) at the end of each sentence and commas at natural breath "
        "points, because the TTS voice pauses on them."
    )
    return text + _cut_hint(cuts)


class _Blocked(RuntimeError):
    """Gemini answered with nothing (blocked / cut off) every time for this piece of audio."""


def _safety_settings(types):
    """Film dialogue (fights, crime, romance) must not be refused: switch the adjustable safety filters off."""
    cats = ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "HARM_CATEGORY_DANGEROUS_CONTENT")
    return [types.SafetySetting(category=c, threshold="BLOCK_NONE") for c in cats]


def _dub_chunk(audio_path: str, offset: float, target: str, attempts: int, cuts: list[float] | None = None,
               mode: str = "recap", chunk_no=0, depth: int = 0, skipped: list | None = None) -> tuple[str | None, list[dict]]:
    """One piece of audio -> (language, segments). If Gemini keeps refusing it (empty answer), the piece is cut in two
    and each half is tried again (up to 2 levels, down to ~25 s); a piece that is still refused is skipped and reported
    in `skipped` ((start, end) seconds) instead of failing the whole video."""
    try:
        return _dub_piece(audio_path, offset, target, attempts, cuts, mode, chunk_no)
    except _Blocked as exc:
        length = _duration(audio_path)
        if depth >= 2 or length < 25:
            print(f"  part {offset:.0f}-{offset + length:.0f}s refused by Gemini ({exc}); skipped", flush=True)
            if skipped is not None:
                skipped.append((offset, offset + length))
            return None, []
        print(f"  part {offset:.0f}-{offset + length:.0f}s refused by Gemini; trying it as two halves", flush=True)
        results = []
        with tempfile.TemporaryDirectory() as tmp:
            for k, (a, b) in enumerate([(0.0, length / 2), (length / 2, length)]):
                piece = os.path.join(tmp, f"half{k}.mp3")
                _run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", audio_path, "-c", "copy", piece])
                results.append(_dub_chunk(piece, offset + a, target, attempts,
                                          [c - a for c in cuts or [] if a <= c < b], mode, f"{chunk_no}{'ab'[k]}",
                                          depth + 1, skipped))
        return next((lang for lang, _ in results if lang), None), [s for _, segs in results for s in segs]


def _dub_piece(audio_path: str, offset: float, target: str, attempts: int,
               cuts: list[float] | None = None, mode: str = "recap", chunk_no=0) -> tuple[str | None, list[dict]]:
    from google.genai import types

    client = _get_client()
    uploaded = client.files.upload(file=audio_path, config={"mime_type": "audio/mpeg"})
    try:
        deadline = time.monotonic() + 600
        while getattr(uploaded.state, "name", str(uploaded.state)) == "PROCESSING":
            if time.monotonic() > deadline:
                raise TimeoutError("Gemini file processing timed out.")
            time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)
        data = None
        for attempt in range(attempts):
            try:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=[uploaded, _prompt(target, cuts, mode)],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json", response_schema=SCHEMA_FULL if mode == "full" else SCHEMA,
                        temperature=0.2, safety_settings=_safety_settings(types),
                        thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET)),
                )
                raw = response.text
                if not raw or not raw.strip():   # blocked / cut off / empty answer: say why, then ask again
                    cand = (getattr(response, "candidates", None) or [None])[0]
                    why = getattr(cand, "finish_reason", None) or getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
                    raise ValueError(f"empty answer from Gemini (reason: {why})")
                data = json.loads(raw)
                break
            except Exception as exc:
                err = str(exc).lower()
                transient = isinstance(exc, ValueError) or any(
                    k in err for k in ("429", "500", "503", "resource_exhausted", "unavailable", "timeout", "timed out", "too_many_requests", "disconnected", "connection"))
                if "per day" in err or "perday" in err:
                    transient = False
                if not transient or attempt == attempts - 1:
                    if isinstance(exc, ValueError) and "empty answer" in str(exc):
                        raise _Blocked(str(exc)) from exc
                    raise RuntimeError(f"Gemini transcription failed: {exc}") from exc
                wait = min(5 * 2 ** attempt, 60) if not isinstance(exc, ValueError) else 2
                print(f"  Gemini problem ({exc.__class__.__name__}: {str(exc)[:120]}); retry {attempt + 1}/{attempts - 1} in {wait}s", flush=True)
                time.sleep(wait)
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass
    segments = []
    for s in data.get("segments", []):
        text = (s.get("translated_text") or "").strip()
        start, end = float(s["start"]) + offset, float(s["end"]) + offset
        if text and end > start:
            seg = {"start": start, "end": end, "source_text": s.get("source_text", ""), "translated_text": text}
            if mode == "full":
                seg.update(speaker=f"{chunk_no}:{(s.get('speaker') or 'S1').strip()}",
                           gender=s.get("gender") or "unknown", age=s.get("age") or "adult",
                           voice_desc=s.get("voice", ""), emotion=s.get("emotion") or "neutral")
            segments.append(seg)
    return data.get("source_language"), segments


def dub(video_path: str, target_language: str, timeout_seconds: int = 600,
        retries: int | None = None, scene_cuts: list[float] | None = None,
        mode: str = "recap", skipped: list | None = None) -> tuple[str | None, list[dict]]:
    """Transcribe the speech, translate it, and return (source_language, segments) with timings in seconds."""
    target = LANGUAGE_NAMES.get(target_language, target_language)
    attempts = retries or int(os.getenv("GEMINI_DUB_RETRIES", "6"))
    with tempfile.TemporaryDirectory() as tmp:
        audio = os.path.join(tmp, "audio.mp3")
        _run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", audio])
        chunks = _plan_chunks(audio, _duration(audio))
        paths = []
        for n, (a, b) in enumerate(chunks):
            if len(chunks) == 1:
                paths.append((audio, 0.0, b))
                continue
            p = os.path.join(tmp, f"chunk{n}.mp3")
            _run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", audio, "-c", "copy", p])
            paths.append((p, a, b))
        print(f"  transcribing {len(paths)} chunk(s) in parallel", flush=True)
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(paths))) as pool:
            results = list(pool.map(
                lambda n_pab: _dub_chunk(n_pab[1][0], n_pab[1][1], target, attempts,
                                         [c - n_pab[1][1] for c in scene_cuts or [] if n_pab[1][1] <= c < n_pab[1][2]],
                                         mode, n_pab[0], 0, skipped),
                enumerate(paths)))

    source = next((lang for lang, _ in results if lang), None)
    segments = sorted((s for _, segs in results for s in segs), key=lambda s: s["start"])
    if not segments:
        raise RuntimeError("Gemini returned no translated timed transcript segments.")
    if mode == "full":
        unify_speakers(segments)
    return source, finish_segments(segments, scene_cuts or [])


def unify_speakers(segments: list[dict]):
    """Speaker labels were given per chunk ("2:S1"). Merge them into whole-film characters "A", "B", ... : one cheap text
    request that sees every chunk's speakers (gender, age, voice, sample lines). Falls back to gender+age grouping."""
    keys: dict[str, dict] = {}
    for sg in segments:
        k = keys.setdefault(sg["speaker"], {"n": 0, "gender": {}, "age": sg.get("age"), "voice": sg.get("voice_desc", ""), "lines": []})
        k["n"] += 1
        k["gender"][sg["gender"]] = k["gender"].get(sg["gender"], 0) + 1
        if len(k["lines"]) < 2:
            k["lines"].append((sg.get("source_text") or "")[:60])
    mapping: dict[str, str] = {}
    if len({k.split(":")[0] for k in keys}) > 1 and len(keys) > 1:
        try:
            from google.genai import types
            from gemini_tts import get_text_client
            desc = "\n".join(f"{key} | gender {max(v['gender'], key=v['gender'].get)} | {v['age']} | voice: {v['voice']} | "
                             f"{v['n']} lines | e.g. {' / '.join(v['lines'])}" for key, v in keys.items())
            ask = ("These speakers were detected separately in consecutive parts of ONE film (key = part:label). Decide which "
                   "keys are the same character (same gender and a matching voice description, consistent with the sample "
                   "lines) and give each distinct character a short id (A, B, C, ...). Keys from the SAME part with different "
                   "labels are always different characters. When unsure, keep them separate.\n" + desc)
            resp = get_text_client().models.generate_content(
                model=MODEL, contents=ask,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.0,
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    response_schema={"type": "array", "items": {"type": "object", "properties": {
                        "key": {"type": "string"}, "character": {"type": "string"}}, "required": ["key", "character"]}}))
            mapping = {m["key"]: str(m["character"]).strip() for m in json.loads(resp.text or "[]") if m.get("key") in keys}
        except Exception as exc:
            print(f"  speaker merge failed ({exc}); grouping by gender and age instead", flush=True)
    if len(mapping) != len(keys):  # no answer, or incomplete: group by gender + age
        mapping = {key: f"{max(v['gender'], key=v['gender'].get)}-{v['age']}" for key, v in keys.items()}
    order = sorted({c for c in mapping.values()}, key=lambda c: -sum(v["n"] for k, v in keys.items() if mapping[k] == c))
    names = {c: chr(65 + i) if i < 26 else f"C{i}" for i, c in enumerate(order)}   # A = most lines
    for sg in segments:
        sg["speaker"] = names[mapping[sg["speaker"]]]
    genders: dict[str, dict] = {}
    for sg in segments:
        g = genders.setdefault(sg["speaker"], {})
        g[sg["gender"]] = g.get(sg["gender"], 0) + 1
    for sg in segments:   # one gender per character (the most frequent known one)
        known = {k: v for k, v in genders[sg["speaker"]].items() if k != "unknown"}
        sg["gender"] = max(known, key=known.get) if known else "unknown"
    counts = {n: sum(1 for s in segments if s["speaker"] == n) for n in sorted(names.values())}
    print(f"  speakers: {len(names)} characters, lines per character: {counts}", flush=True)


def finish_segments(segments: list[dict], cuts: list[float]) -> list[dict]:
    """Snap segment starts/ends onto scene cuts (so a voice line begins with its scene), then measure
    characters-per-second and flag lines that are probably too long for their slot."""
    from scene_cuts import snap

    prev_end = 0.0
    for sg in segments:
        start, end = snap(sg["start"], cuts), snap(sg["end"], cuts)
        if start >= prev_end - 0.05 and end > start + 0.2:
            sg["start"], sg["end"] = max(start, prev_end), end
        prev_end = sg["end"]
    flagged = 0
    for sg in segments:
        sg["cps"] = round(len(sg["translated_text"]) / max(sg["end"] - sg["start"], 0.2), 1)
        sg["too_long"] = sg["cps"] > CPS * 1.35  # more than the voice can be sped up to
        flagged += sg["too_long"]
    print(f"  {len(segments)} segments, {flagged} flagged too long for their slot (> {CPS * 1.35:.0f} chars/s)", flush=True)
    return segments
