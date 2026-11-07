"""Make the same Burmese line with and without a delivery style, so you can LISTEN and compare (1-2 TTS requests each).
Run: python test_tts_style.py   -> style_samples/plain.wav, style_samples/styled_*.wav
Check the styled ones: is the instruction read aloud? Does it sound more like a recap narrator? Then set TTS_STYLE in .env."""
import os

import gemini_tts

LINE = "ဒီအချိန်မှာပဲ သူ့ရဲ့ လျှို့ဝှက်ချက်တစ်ခု ပေါ်လာတော့တယ်။ ဘယ်သူမှ မမျှော်လင့်ခဲ့ဘူး။"
STYLES = {
    "recap": "Read as an energetic, gripping movie-recap storyteller, fast and lively:",
    "calm": "Say in a warm, natural, conversational storytelling voice:",
}
os.makedirs("style_samples", exist_ok=True)
gemini_tts.STYLE = ""
gemini_tts.synthesize_to_file(LINE, "style_samples/plain.wav")
for name, style in STYLES.items():
    gemini_tts.STYLE = style
    gemini_tts.synthesize_to_file(LINE, f"style_samples/styled_{name}.wav")
print("done: open the files in style_samples/ and compare")
