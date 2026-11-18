"""Offline test: the fit step counts on the timeline's voice speed-up instead of cutting every line to normal speed; Standard (Azure) starts from
Azure's own duration numbers. Run: python test_fit_stretch.py"""
import duration_model as dm
import pipeline as P

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

keep, tgt = P.fit_stretch({"allow_voice_speedup": True, "max_voice_speedup": 1.35})
ok(keep == 1.35 and 1.1 < tgt < 1.25, f"speed-up on: keep {keep}, rewrite target {tgt:.2f}x the scene")
ok(P.fit_stretch({"allow_voice_speedup": False, "max_voice_speedup": 1.35}) == (1.0, 0.95), "speed-up off: the old rule (fit at normal speed)")
ok(P.fit_stretch({"allow_voice_speedup": True, "max_voice_speedup": 9})[0] == 1.5, "the speed-up is capped at 1.5 like the timeline")
s = P.fit_stretch({"allow_voice_speedup": True, "max_voice_speedup": 1.35})
up = 2.5
ok(P._plan(3.2, up, up, lengthen=False, stretch=s) is None, "a line 1.28x its scene is kept (the timeline speeds it up)")
ok(P._plan(3.2, up, up, lengthen=False) is not None, "...it used to be cut")
mode, t = P._plan(4.0, up, up, lengthen=False, stretch=s)
ok(mode == "shorten" and up * 1.1 < t < up * 1.25, f"a line 1.6x its scene is cut to {t:.2f}s (not to {up * 0.95:.2f}s)")
ok(P._plan(1.0, up, up, stretch=s) == ("lengthen", up), "a short line is still lengthened")
ok(dm.default_for("standard") == dm.AZURE and dm.default_for("premium") == dm.DEFAULT and dm.default_for(None) == dm.DEFAULT, "default voice timing by quality")
ok(dm.predict("ပွဲဖျက်ဖို့ လုပ်နေတာပါ။", dm.AZURE) > dm.predict("ပွဲဖျက်ဖို့ လုပ်နေတာပါ။", dm.DEFAULT), "Azure predicts longer than the Gemini default")
print("ALL OK")
