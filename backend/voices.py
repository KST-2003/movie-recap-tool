"""Gemini TTS prebuilt voices (gender per Google's docs; verify by ear on the current model)."""
FEMALE = ["Zephyr", "Kore", "Leda", "Aoede", "Callirrhoe", "Autonoe", "Despina", "Erinome",
          "Laomedeia", "Achernar", "Gacrux", "Pulcherrima", "Vindemiatrix", "Sulafat"]
MALE = ["Puck", "Charon", "Fenrir", "Orus", "Enceladus", "Iapetus", "Umbriel", "Algieba",
        "Algenib", "Rasalgethi", "Alnilam", "Schedar", "Achird", "Zubenelgenubi", "Sadachbia", "Sadaltager"]

VOICES = [{"name": n, "gender": "female"} for n in FEMALE] + [{"name": n, "gender": "male"} for n in MALE]
VOICE_NAMES = {v["name"] for v in VOICES}
SAMPLE_TEXT = "မင်္ဂလာပါ၊ ဒီဗီဒီယိုကို မြန်မာလို ပြန်ပြောပြထားတာပါ။"
