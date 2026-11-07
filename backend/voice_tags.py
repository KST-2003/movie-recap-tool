"""Voice catalogue for casting. `generate_voice_tags.py` lets Gemini LISTEN to each pre-generated sample once and writes
short tags (gender, age feel, pitch, timbre, energy) to voice_tags.json. At casting time ONE text request per film
(`cast`) matches the film's characters (gender / age / voice description from the roster pass) to those tags."""
import json
import os

import looks
import voices as V

TAGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_tags.json")
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_samples")
MODEL = os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash")
SCHEMA = {"type": "object", "properties": {
    "gender": {"type": "string", "enum": ["male", "female"]},
    "age": {"type": "string", "enum": ["child", "young", "adult", "middle-aged", "elderly"]},
    "pitch": {"type": "string", "enum": ["very low", "low", "medium", "high", "very high"]},
    "timbre": {"type": "string"},      # 2-5 words: gravelly, smooth, breathy, bright, warm, nasal...
    "energy": {"type": "string", "enum": ["calm", "neutral", "lively"]},
}, "required": ["gender", "age", "pitch", "timbre", "energy"]}


def load() -> dict:
    try:
        with open(TAGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def tag_voice(name: str) -> dict:
    from google.genai import types
    from gemini_tts import get_text_client
    with open(os.path.join(SAMPLES_DIR, f"{name}.wav"), "rb") as f:
        audio = types.Part.from_bytes(data=f.read(), mime_type="audio/wav")
    resp = get_text_client().models.generate_content(
        model=MODEL, contents=[audio, "Describe the VOICE of this speaker (not the words): gender, how old the speaker sounds, "
                                      "pitch, timbre in 2-5 words, and energy."],
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=SCHEMA, temperature=0.0,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return fix(name, json.loads(resp.text))


# Google's own one-word style per voice (their docs), from memory: the most reliable description we have.
GOOGLE_STYLE = {
    "Zephyr": "bright", "Puck": "upbeat", "Charon": "informative", "Kore": "firm", "Fenrir": "excitable", "Leda": "youthful",
    "Orus": "firm", "Aoede": "breezy", "Callirrhoe": "easy-going", "Autonoe": "bright", "Enceladus": "breathy", "Iapetus": "clear",
    "Umbriel": "easy-going", "Algieba": "smooth", "Despina": "smooth", "Erinome": "clear", "Algenib": "gravelly",
    "Rasalgethi": "informative", "Laomedeia": "upbeat", "Achernar": "soft", "Alnilam": "firm", "Schedar": "even",
    "Gacrux": "mature", "Pulcherrima": "forward", "Achird": "friendly", "Zubenelgenubi": "casual", "Vindemiatrix": "gentle",
    "Sadachbia": "lively", "Sadaltager": "knowledgeable", "Sulafat": "warm",
}


def fix(name: str, t: dict) -> dict:
    """Listening got gender wrong for 5 of 30 voices and its pitch words are vague, so: gender = Google's list, pitch = measured
    median F0 of the sample (pitch.py), plus Google's style word. Age / timbre / energy stay as heard (unverified)."""
    import pitch
    t = dict(t)
    t["gender"] = "female" if name in V.FEMALE else "male"
    hz = pitch.voice_reference(name)
    t["f0_hz"] = round(hz) if hz else None
    t["google_style"] = GOOGLE_STYLE.get(name, "")
    return t


def line(name: str, t: dict) -> str:
    hz = f"{t['f0_hz']} Hz" if t.get("f0_hz") else t.get("pitch")
    return f"{name} | {t.get('gender')} | sounds {t.get('age')} | pitch {hz} | {t.get('google_style', '')}, {t.get('timbre')} | {t.get('energy')}"


def cast(characters: list[dict], tags: dict | None = None) -> dict:
    """ONE text request: characters [{id, gender, age, desc, lines}] -> {id: voice name}. Raises on any failure (caller falls back)."""
    from google.genai import types
    from gemini_tts import get_text_client
    tags = tags or load()
    if len(tags) < 10:
        raise RuntimeError("voice_tags.json missing: run generate_voice_tags.py")
    catalogue = "\n".join(line(n, t) for n, t in tags.items() if n in V.VOICE_NAMES)
    creature_lines = "\n".join(f"look:{i} | {lab} (a real voice with a special delivery)" for i, g, lab, _b, _s in looks.LOOKS if i in looks.AUTO_IDS)
    chars = "\n".join(f"{c['id']} | gender {c.get('gender', 'unknown')} | age {c.get('age', 'adult')} | "
                      f"sounds: {c.get('desc') or '-'} | {c.get('lines', 0)} lines" for c in characters)
    prompt = (
        "You cast voice actors for a dubbed film. VOICES (name | gender | age | pitch | timbre | energy):\n" + catalogue +
        "\n\nSPECIAL LOOKS (use one ONLY for a character that is clearly not an ordinary human: monster, animal, robot, ghost, alien, "
        "baby... as the description says; never for ordinary people):\n" + creature_lines +
        "\n\nCHARACTERS (id | gender | age | how the original voice sounds | lines):\n" + chars +
        "\n\nGive every character ONE voice. Rules: never use the same voice for two characters; the voice's gender must match "
        "the character's when it is known; match age (an old man must get an old-sounding voice, a child a young one), pitch "
        "and the described sound (gravelly, soft, shrill...). Characters with more lines get the most fitting voices.")
    schema = {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "voice": {"type": "string"}}, "required": ["id", "voice"]}}
    resp = get_text_client().models.generate_content(
        model=MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.0,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return {d["id"]: d["voice"] for d in json.loads(resp.text) if d.get("voice") in V.VOICE_NAMES or d.get("voice") in {f"look:{i}" for i in looks.AUTO_IDS}}
