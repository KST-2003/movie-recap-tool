"""Quick check that your Gemini key can speak Burmese:  GEMINI_API_KEY=... python test_gemini_tts.py"""
import subprocess
import sys

from gemini_tts import MODEL, synthesize_to_file

text = "မင်္ဂလာပါ၊ ဒီဗီဒီယိုကို မြန်မာလို ပြန်ပြောပြထားတာပါ။"
synthesize_to_file(text, "gemini_test.wav")
dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", "gemini_test.wav"],
                     capture_output=True, text=True).stdout.strip()
print(f"OK: {MODEL} wrote gemini_test.wav ({dur}s). Play it to check the Burmese sounds right.")
