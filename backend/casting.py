"""Full-movie mode: give every character ONE voice for the whole film, so voices never change between scenes.

- the most talkative character (A) gets the voice the user picked, if the gender fits (or is unknown);
- every other character gets the next unused voice of their gender (female / male lists in voices.py);
- unknown gender takes whichever list has been used less; when a list is used up, voices are reused;
- user overrides (the editor's "Characters" panel) always win."""
import voices as V

DEFAULT_VOICE = "Kore"


def _gender_of(voice: str) -> str:
    return "female" if voice in V.FEMALE else "male"


def characters_of(segments: list[dict]) -> list[dict]:
    """[{id, gender, age, desc, lines}] per character, for the casting request."""
    out: dict[str, dict] = {}
    for sg in segments:
        sid = sg.get("speaker") or "A"
        c = out.setdefault(sid, {"id": sid, "lines": 0, "gender": "unknown", "desc": "", "ages": {}})
        c["lines"] += 1
        age = sg.get("age") or "adult"
        c["ages"][age] = c["ages"].get(age, 0) + 1
        if sg.get("gender") in ("male", "female") and c["gender"] == "unknown":
            c["gender"] = sg["gender"]
        c["desc"] = c["desc"] or sg.get("voice_desc") or ""
    for c in out.values():
        ages = c.pop("ages")
        c["age"] = max(ages, key=ages.get)
    return list(out.values())


def llm_choice(segments: list[dict], skip: set | None = None) -> dict:
    """Ask Gemini (ONE text request) which voice suits each character. Any failure -> {} (the rules decide instead)."""
    try:
        import voice_tags
        chars = [c for c in characters_of(segments) if c["id"] not in (skip or set())]
        if len(chars) < 2:
            return {}
        picked = voice_tags.cast(chars)
        print("  voice matching (Gemini): " + ", ".join(f"{k}={v}" for k, v in picked.items()), flush=True)
        return picked
    except Exception as exc:
        print(f"  voice matching skipped ({str(exc)[:100]}); using the built-in rules", flush=True)
        return {}


def assign_voices(segments: list[dict], chosen_voice: str, overrides: dict | None = None, suggested: dict | None = None) -> dict:
    """Sets sg["voice"] on every segment and returns {speaker: {"voice", "gender", "lines"}} (A = most lines)."""
    overrides = {k: v for k, v in (overrides or {}).items() if v in V.VOICE_NAMES}
    chosen = DEFAULT_VOICE if chosen_voice in (None, "", "su") else chosen_voice
    lines: dict[str, int] = {}
    gender: dict[str, str] = {}
    ages: dict[str, dict] = {}
    for sg in segments:
        a = ages.setdefault(sg.get("speaker") or "A", {})
        a[sg.get("age") or "adult"] = a.get(sg.get("age") or "adult", 0) + 1
    for sg in segments:
        sid = sg.get("speaker") or "A"
        sg["speaker"] = sid
        lines[sid] = lines.get(sid, 0) + 1
        if sg.get("gender") in ("male", "female"):
            gender.setdefault(sid, sg["gender"])
    order = sorted(lines, key=lambda s: (-lines[s], s))
    used: list[str] = []
    result: dict[str, dict] = {}
    for sid in order:
        g = gender.get(sid, "unknown")
        if sid in overrides:
            voice = overrides[sid]
        elif (not suggested or sid == order[0]) and chosen not in used and g in ("unknown", _gender_of(chosen)) and not any(
                r["voice"] == chosen for r in result.values()):
            voice = chosen
        else:
            if g == "unknown":
                g = "female" if sum(_gender_of(u) == "female" for u in used) <= sum(_gender_of(u) == "male" for u in used) else "male"
            pool = V.FEMALE if g == "female" else V.MALE
            sug = (suggested or {}).get(sid)
            age = max(ages.get(sid) or {"adult": 1}, key=lambda k: ages[sid][k])
            # first the voices that suit this character's age (an old man must not get a young man's voice), then any free one
            free = [v for v in V.AGE_VOICES.get((g, age), []) if v not in used and v != chosen] \
                or [v for v in pool if v not in used and v != chosen]
            voice = free[0] if free else pool[len([u for u in used if u in pool]) % len(pool)]
            # Gemini's pick wins when it is a free voice of the right gender (it may have been told nothing about gender: check)
            if sug and sug not in used and sug != chosen and (gender.get(sid, "unknown") in ("unknown", _gender_of(sug))):
                voice = sug
        used.append(voice)
        result[sid] = {"voice": voice, "gender": gender.get(sid, _gender_of(voice) if sid in overrides else "unknown"),
                       "lines": lines[sid], "age": max(ages.get(sid) or {"adult": 1}, key=lambda k: ages[sid][k])}
    for sg in segments:
        sg["voice"] = result[sg["speaker"]]["voice"]
    return result
