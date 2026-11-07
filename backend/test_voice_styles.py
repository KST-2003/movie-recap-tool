"""Can Gemini TTS make baby / old / monster / alien / animal voices? It has only 30 prebuilt voices, but the text can carry a
performance instruction. This makes ONE Burmese line in many 'character looks' so you can LISTEN (about 10 requests).
Run: python test_voice_styles.py  -> character_samples/<look>_<voice>.wav"""
import os
import time

from dotenv import load_dotenv

load_dotenv()
import gemini_tts  # noqa: E402

LINE = "ဒီနေရာကို မင်းတို့ ဘယ်သူမှ ထွက်သွားလို့ မရတော့ဘူး။"
LOOKS = {   # name: (voice, instruction placed before the line)
    "baby": ("Leda", "Say in the high, cute voice of a small baby-like child"),
    "old_man": ("Algenib", "Say in the weak, shaky, hoarse voice of a very old man"),
    "old_woman": ("Gacrux", "Say in the thin, trembling voice of a very old woman"),
    "monster": ("Charon", "Say in a deep, growling, inhuman monster voice"),
    "alien": ("Puck", "Say in a strange, robotic, otherworldly alien voice"),
    "animal": ("Zubenelgenubi", "Say like a small talking animal, squeaky and playful"),
    "ghost": ("Vindemiatrix", "Say in an eerie, hollow, whispering ghost voice"),
    "robot": ("Orus", "Say in a flat, metallic robot voice"),
}
os.makedirs("character_samples", exist_ok=True)
for name, (voice, instr) in LOOKS.items():
    path = f"character_samples/{name}_{voice}.wav"
    try:
        gemini_tts.synthesize_to_file(f"{instr}: {LINE}", path, voice)
        print("ok", path)
    except Exception as exc:
        print("FAILED", name, str(exc)[:120])
    time.sleep(1)
print("done: listen to character_samples/. Is the instruction read aloud? Does the voice really change?")
