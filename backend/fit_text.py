"""Shorten a translated line so its voice-over fits the time its source scene allows."""
import os

LANGUAGE_NAMES = {"my": "Burmese", "th": "Thai", "zh": "Chinese", "en": "English"}
MODEL = os.getenv("FIT_TEXT_MODEL", "claude-haiku-5-5")


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def _shorten_gemini(prompt: str, system: str) -> str:
    from google.genai import types
    from gemini_tts import _get_client
    response = _get_client().models.generate_content(
        model=os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash"),
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.3,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)),
    )
    return (response.text or "").strip()


def _ask(system: str, user: str, current_text: str) -> str:
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=600, system=system, messages=[{"role": "user", "content": user}])
        text = "".join(block.text for block in msg.content if block.type == "text").strip()
    else:
        text = _shorten_gemini(user, system)
    return text or current_text


def shorten(source_text: str, current_text: str, language: str, current_s: float, budget_s: float) -> str:
    """Rewrite current_text so it is spoken in about budget_s seconds instead of current_s (shorter)."""
    ratio = max(0.3, min(budget_s / current_s, 0.98))
    target_chars = max(4, int(len(current_text) * ratio * 0.95))
    lang = LANGUAGE_NAMES.get(language, language)
    system = (
        f"You edit {lang} voice-over lines for movie-recap videos so they fit a fixed time slot. "
        "Keep the full meaning, names, numbers and the key plot fact; drop only filler and repetition; keep it a "
        "complete, natural sentence in a spoken, engaging storyteller tone (not clipped or robotic). "
        "Reply with the rewritten line only: no quotes, no notes."
    )
    user = (
        f"Original (source language): {source_text}\n"
        f"Current {lang} line ({len(current_text)} chars, speaks in {current_s:.1f}s): {current_text}\n"
        f"Rewrite it to about {target_chars} characters so it speaks in at most {budget_s:.1f}s."
    )
    return _ask(system, user, current_text)


def lengthen(source_text: str, current_text: str, language: str, current_s: float, target_s: float) -> str:
    """Rewrite current_text so it is spoken in about target_s seconds instead of current_s (longer, no dead air)."""
    ratio = min(max(target_s / current_s, 1.05), 1.8)
    target_chars = int(len(current_text) * ratio * 0.97)
    lang = LANGUAGE_NAMES.get(language, language)
    system = (
        f"You edit {lang} voice-over lines for movie-recap videos. The line is too SHORT for its time slot and "
        "would leave dead air. Lengthen it naturally with fuller wording that stays faithful to the original: "
        "restore details from the original that were dropped, and add natural connecting words and storyteller "
        "phrasing. NEVER add facts, names, numbers or events that are not in the original, and never change the "
        "meaning. Keep complete, natural sentences in a spoken, engaging storyteller tone. "
        "Reply with the rewritten line only: no quotes, no notes."
    )
    user = (
        f"Original (source language): {source_text}\n"
        f"Current {lang} line ({len(current_text)} chars, speaks in {current_s:.1f}s): {current_text}\n"
        f"Rewrite it to about {target_chars} characters so it speaks in about {target_s:.1f}s."
    )
    return _ask(system, user, current_text)


# ---------- many lines in ONE request (this is what keeps long videos fast) ----------

BATCH_LINES = int(os.getenv("FIT_BATCH_LINES", "20"))   # lines per LLM request; batches run in parallel

_BATCH_SYSTEM = (
    "You edit {lang} voice-over lines for movie-recap videos so each line is spoken in its own time slot. "
    "You get a JSON list; for every item rewrite `current` to about `target_chars` characters. "
    "mode=shorten: drop only filler and repetition, pick shorter common words. "
    "mode=lengthen: the line would leave dead air; add natural connecting words and storyteller phrasing and restore "
    "details of `source` that were dropped. ALWAYS keep the full meaning, names and numbers; NEVER add facts that are "
    "not in `source`; keep complete, natural sentences in a spoken, engaging storyteller tone (not clipped or robotic). "
    "The items are consecutive lines of one story, so keep wording consistent. "
    'Reply with JSON only: a list of {{"id": <same id>, "text": "<rewritten line>"}} for every item.'
)


def _parse_json_list(text: str) -> list[dict]:
    import json
    import re
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    data = json.loads(text)
    return data if isinstance(data, list) else data.get("items", [])


def _rewrite_chunk(items: list[dict], language: str) -> dict[int, str]:
    import json
    lang = LANGUAGE_NAMES.get(language, language)
    system = _BATCH_SYSTEM.format(lang=lang)
    payload = json.dumps(items, ensure_ascii=False)
    if os.getenv("ANTHROPIC_API_KEY"):
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model=MODEL, max_tokens=8000, system=system, messages=[{"role": "user", "content": payload}])
        raw = "".join(b.text for b in msg.content if b.type == "text")
    else:
        from google.genai import types
        from gemini_tts import _get_client
        schema = {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
                                             "required": ["id", "text"]}}
        response = _get_client().models.generate_content(
            model=os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash"), contents=payload,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.3,
                                               response_mime_type="application/json", response_schema=schema,
                                               thinking_config=types.ThinkingConfig(thinking_budget=0)))
        raw = response.text or "[]"
    return {int(r["id"]): str(r["text"]).strip() for r in _parse_json_list(raw) if str(r.get("text", "")).strip()}


def rewrite_many(items: list[dict], language: str) -> dict[int, str]:
    """items: [{id, source, current, mode, target_chars}] -> {id: new text}. Missing ids = keep the current line."""
    from concurrent.futures import ThreadPoolExecutor
    chunks = [items[i:i + BATCH_LINES] for i in range(0, len(items), BATCH_LINES)]
    out: dict[int, str] = {}

    def run(chunk):
        try:
            return _rewrite_chunk(chunk, language)
        except Exception as exc:  # one failed chunk must not fail the job: those lines just keep their text
            print(f"  fit rewrite request failed ({exc})", flush=True)
            return {}

    with ThreadPoolExecutor(max_workers=min(8, max(len(chunks), 1))) as pool:
        for part in pool.map(run, chunks):
            out.update(part)
    return out
