"""Gemini TTS prebuilt voices (gender per Google's docs; verify by ear on the current model)."""
FEMALE = ["Zephyr", "Kore", "Leda", "Aoede", "Callirrhoe", "Autonoe", "Despina", "Erinome",
          "Laomedeia", "Achernar", "Gacrux", "Pulcherrima", "Vindemiatrix", "Sulafat"]
MALE = ["Puck", "Charon", "Fenrir", "Orus", "Enceladus", "Iapetus", "Umbriel", "Algieba",
        "Algenib", "Rasalgethi", "Alnilam", "Schedar", "Achird", "Zubenelgenubi", "Sadachbia", "Sadaltager"]

# Which voices suit which age (Google's style words + measured pitch of our samples; verify by ear). Order = preference.
AGE_VOICES = {
    ("male", "elderly"): ["Algenib", "Charon", "Algieba", "Sadaltager", "Orus", "Umbriel"],     # gravelly / deep / knowledgeable
    ("male", "young"): ["Puck", "Sadachbia", "Fenrir", "Zubenelgenubi", "Achird"],              # upbeat / lively / light
    ("male", "adult"): ["Orus", "Alnilam", "Schedar", "Iapetus", "Enceladus", "Umbriel", "Achird"],
    ("female", "elderly"): ["Gacrux", "Vindemiatrix", "Achernar", "Sulafat"],                    # mature / gentle / soft
    ("female", "young"): ["Leda", "Aoede", "Laomedeia", "Zephyr", "Autonoe"],                    # youthful / breezy / bright
    ("female", "adult"): ["Kore", "Erinome", "Despina", "Callirrhoe", "Sulafat", "Pulcherrima"],
}
AGE_VOICES[("male", "child")] = AGE_VOICES[("male", "young")]
AGE_VOICES[("female", "child")] = AGE_VOICES[("female", "young")]

VOICES = [{"name": n, "gender": "female"} for n in FEMALE] + [{"name": n, "gender": "male"} for n in MALE]
VOICE_NAMES = {v["name"] for v in VOICES}
SAMPLE_TEXT = "မင်္ဂလာပါ၊ ဒီဗီဒီယိုကို မြန်မာလို ပြန်ပြောပြထားတာပါ။"
