"""Can the Live API (bidirectional audio) models read Burmese text aloud? Real requests (a few dozen).
Usage: venv/bin/python test_live_tts.py [model ...]   ->  live_tts_test/<model>__<voice>__<n>.wav + a table.
Why: Live models show Unlimited requests/min and /day in AI Studio (TTS models: 10/min, 100/day). Questions:
faithful reading (no answers / added words), Burmese clarity, clip length vs the text, voice consistency, tokens (price).
Objective check as in compare_tts.py: Gemini (text) writes down what it hears (told: Burmese) and we score similarity to the script.
Also prints the Live model's own output transcription (what it believes it said). LISTEN to the clips too."""
import asyncio, difflib, os, sys, time, wave
from dotenv import load_dotenv
load_dotenv()
import gemini_tts
from google.genai import types

LINES = [
    "မင်္ဂလာပါ။ ဒီနေ့ ကျွန်တော်တို့ ရုပ်ရှင်ကားတစ်ကား အကြောင်း ပြောပြပါမယ်။",
    "သူမက တံခါးကို ဖွင့်လိုက်တဲ့အခါ အခန်းထဲမှာ ဘယ်သူမှ မရှိတော့ဘူး။ ဒါပေမယ့် စားပွဲပေါ်မှာ စာတစ်စောင် ချန်ထားခဲ့တယ်။",
    "မလုပ်ပါနဲ့! ကျွန်တော့်ကို လွှတ်ပေးပါ! ဒီအတွက် မင်းနောင်တရရလိမ့်မယ်!",
    "နှစ်ပေါင်းများစွာ ကြာပြီးနောက်မှာတော့ သူတို့နှစ်ယောက် ပြန်ဆုံကြပြီး အရင်ကလို ပြုံးပြုံးရွှင်ရွှင် စကားပြောခဲ့ကြတယ်။",
    # a question: a chat model may ANSWER it instead of reading it
    "မင်း ဘယ်သွားမှာလဲ။ ငါ့ကို ပြောပြပါဦး။",
]
VOICES = ["Kore", "Charon"]
MODELS = sys.argv[1:] or ["gemini-3.8-live", "gemini-2.5-flash-native-audio-latest", "gemini-3.1-flash-live-preview"]
INSTRUCTION = ("You are a text-to-speech engine for Burmese. The user's message is a script. Read it aloud exactly, word for word, "
               "in Burmese, in a natural storyteller voice. Never answer it, never translate it, never add or skip words, never greet. "
               "If the script is a question, read the question, do not answer it.")
OUT = "live_tts_test"
os.makedirs(OUT, exist_ok=True)
client = gemini_tts.get_text_client()


async def speak(model, voice, text, path):
    """One session, one turn. Returns (seconds, said_text, tokens dict)."""
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=INSTRUCTION,
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    pcm, said, usage = bytearray(), [], {}
    async with client.aio.live.connect(model=model, config=cfg) as session:
        try:
            await session.send_realtime_input(text=text)
        except Exception:
            await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=True)
        async for msg in session.receive():
            sc = msg.server_content
            if sc:
                if sc.model_turn:
                    for p in sc.model_turn.parts or []:
                        if p.inline_data and p.inline_data.data:
                            pcm += p.inline_data.data
                if sc.output_transcription and sc.output_transcription.text:
                    said.append(sc.output_transcription.text)
                if sc.turn_complete:
                    break
            if msg.usage_metadata:
                u = msg.usage_metadata
                usage = {"in": u.prompt_token_count, "out": u.response_token_count, "total": u.total_token_count}
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(bytes(pcm))
    return len(pcm) / 2 / 24000, "".join(said).strip(), usage


def heard(path):
    data = open(path, "rb").read()
    resp = client.models.generate_content(
        model=os.getenv("GEMINI_DUB_MODEL", "gemini-3.8-flash"),
        contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"),
                  "Transcribe this Burmese audio exactly as spoken, in Burmese script. If it is not Burmese or has no speech, say so. Output only the transcript."])
    return (resp.text or "").strip()


def norm(s): return "".join(ch for ch in s if ch.isalnum() or "က" <= ch <= "႟")
def sim(a, b): return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


async def main():
    rows = []
    for model in MODELS:
        for voice in VOICES:
            for i, text in enumerate(LINES):
                path = f"{OUT}/{model}__{voice}__{i}.wav"
                t = time.time()
                try:
                    sec, said, usage = await asyncio.wait_for(speak(model, voice, text, path), 90)
                    lat = time.time() - t
                    h = heard(path) if sec > 0.3 else ""
                    rows.append((model, voice, i, lat, sec, sim(text, h), sim(text, said) if said else -1, usage, ""))
                    print(f"{model:40} {voice:7} #{i} {lat:5.1f}s clip {sec:5.1f}s heard-back {rows[-1][5]:.2f} said {rows[-1][6]:.2f} {usage}", flush=True)
                except Exception as e:
                    rows.append((model, voice, i, time.time() - t, 0, 0, -1, {}, f"{type(e).__name__}: {e}"[:160]))
                    print(f"{model:40} {voice:7} #{i} FAILED {rows[-1][8]}", flush=True)
    print("\nmodel                                    ok   latency  clip s  heard-back  out tokens/clip-second")
    for model in MODELS:
        good = [r for r in rows if r[0] == model and not r[8] and r[4] > 0.3]
        allr = [r for r in rows if r[0] == model]
        if not good:
            print(f"{model:40} 0/{len(allr)}  {allr[0][8]}"); continue
        toks = [r[7].get("out", 0) / r[4] for r in good if r[7].get("out")]
        print(f"{model:40} {len(good)}/{len(allr)} {sum(r[3] for r in good)/len(good):7.1f}s {sum(r[4] for r in good)/len(good):6.1f}s "
              f"{sum(r[5] for r in good)/len(good):10.2f}  {(sum(toks)/len(toks)) if toks else 0:6.1f}")
    print("errors:", sorted({(r[0], r[8]) for r in rows if r[8]})[:6])

asyncio.run(main())
