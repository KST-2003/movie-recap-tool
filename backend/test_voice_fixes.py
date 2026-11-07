"""Offline: age-aware casting, mislabel ("sandwich") merge, pitch drift guard. Run: python test_voice_fixes.py"""
import casting, gemini_dub, pitch, voices as V

# 1. an old man gets an old-man voice, a young woman a young one; the user's voice still goes to the main character
segs = ([{"speaker": "A", "gender": "male", "age": "young", "start": i} for i in range(10)]
        + [{"speaker": "B", "gender": "male", "age": "elderly", "start": 20 + i} for i in range(6)]
        + [{"speaker": "C", "gender": "female", "age": "young", "start": 40 + i} for i in range(4)])
r = casting.assign_voices(segs, "Puck")
print({k: v["voice"] for k, v in r.items()})
assert r["A"]["voice"] == "Puck" and r["B"]["voice"] in V.AGE_VOICES[("male", "elderly")] and r["C"]["voice"] in V.AGE_VOICES[("female", "young")]

# 2. three "female" lines that only occur inside the hero's run are the hero (a system panel read aloud)
def line(sp, g, t): return {"speaker": sp, "gender": g, "start": t, "translated_text": "x"}
segs = [line("A", "male", t) for t in range(0, 6)] + [line("E", "female", 6), line("A", "male", 7), line("E", "female", 8),
        line("A", "male", 9), line("A", "male", 10)] + [line("B", "male", 20 + t) for t in range(5)]
gemini_dub.merge_minor_speakers(segs)
assert {s["speaker"] for s in segs} == {"A", "B"} and all(s["gender"] == "male" for s in segs if s["speaker"] == "A"), segs
# a real cameo (between two DIFFERENT speakers) stays
segs = [line("A", "male", t) for t in range(6)] + [line("D", "female", 6)] + [line("B", "male", 7 + t) for t in range(6)]
gemini_dub.merge_minor_speakers(segs)
assert "D" in {s["speaker"] for s in segs}

# 3. pitch guard on real voice samples: Kore's clip is not Puck's voice, Puck's own clip is
bad, got, ref = pitch.drifted("voice_samples/Kore.wav", "Puck")
ok, _, _ = pitch.drifted("voice_samples/Puck.wav", "Puck")
print("Kore as Puck:", bad, got, ref, "| Puck as Puck:", ok)
assert bad and not ok
print("ALL OK")


# Gemini voice matching: its pick is used for characters other than A (A keeps the user's voice if the gender fits); invalid picks fall back
import casting as _c
segs = [{"speaker": "A", "gender": "male", "age": "adult"}] * 5 + [{"speaker": "B", "gender": "male", "age": "elderly"}] * 3 + \
       [{"speaker": "C", "gender": "female", "age": "child"}] * 2
sp = _c.assign_voices([dict(s) for s in segs], "Orus", None, {"A": "Charon", "B": "Enceladus", "C": "Callirrhoe"})
assert sp["A"]["voice"] == "Orus" and sp["B"]["voice"] == "Enceladus" and sp["C"]["voice"] == "Callirrhoe", sp
sp = _c.assign_voices([dict(s) for s in segs], "Orus", None, {"B": "Leda", "C": "Orus"})   # wrong gender / the chosen voice: ignored
assert sp["B"]["voice"] != "Leda" and sp["C"]["voice"] != "Orus", sp
import voice_tags as _vt
assert len(_vt.load()) == 30 and all(t.get("f0_hz") for t in _vt.load().values())
print("llm casting ALL OK")

import looks as _l
assert _l.is_look("look:monster") and not _l.is_look("look:nope") and not _l.is_look("Kore") and _l.resolve("look:monster")[0] == "Charon"
sp = _c.assign_voices([dict(s) for s in segs], "Orus", None, {"B": "look:ghost"})
assert sp["B"]["voice"] == "look:ghost", sp   # a look suggestion is accepted whatever the gender label
txt = _l.compose("Say in a deep, growling, inhuman monster voice", "ဟယ်လို")
assert txt.endswith("#### TRANSCRIPT\nဟယ်လို") and "Speak in a deep" in txt and "Say " not in txt
import pipeline as _p
assert _p.clip_name("a", "look:monster") != _p.clip_name("a", "Charon")
print("looks ALL OK")
assert "Say fearfully" not in _l.compose_emotion("fearfully", "x") and _l.compose_emotion("fearfully", "x").endswith("#### TRANSCRIPT\nx")
print("emotion format ok")
