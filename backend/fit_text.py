"""Shorten a translated line so its voice-over fits the time its source scene allows."""
import os

LANGUAGE_NAMES = {"my": "Burmese", "th": "Thai", "zh": "Chinese", "en": "English"}
MODEL = os.getenv("FIT_TEXT_MODEL", "claude-haiku-5-5")


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def shorten(source_text: str, current_text: str, language: str, current_s: float, budget_s: float) -> str:
    """Rewrite current_text so it is spoken in about budget_s seconds instead of current_s."""
    import anthropic

    ratio = max(0.3, min(budget_s / current_s, 0.98))
    target_chars = max(4, int(len(current_text) * ratio * 0.95))
    lang = LANGUAGE_NAMES.get(language, language)
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=(
            f"You edit {lang} voice-over lines for movie-recap videos so they fit a fixed time slot. "
            "Keep the meaning, names and the key plot fact; drop filler and repetition; keep the tone natural "
            "and spoken. Reply with the rewritten line only: no quotes, no notes."
        ),
        messages=[{
            "role": "user",
            "content": (
                f"Original (source language): {source_text}\n"
                f"Current {lang} line ({len(current_text)} chars, speaks in {current_s:.1f}s): {current_text}\n"
                f"Rewrite it to about {target_chars} characters so it speaks in at most {budget_s:.1f}s."
            ),
        }],
    )
    text = "".join(block.text for block in msg.content if block.type == "text").strip()
    return text or current_text
