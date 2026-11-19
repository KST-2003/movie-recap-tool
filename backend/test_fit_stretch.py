"""Offline test: the fit step counts on the timeline's voice speed-up instead of cutting every line to normal speed; Standard (Azure) starts from
Azure's own duration numbers. Run: python test_fit_stretch.py"""
import duration_model as dm
import pipeline as P

def ok(c, m):
    print(("PASS " if c else "FAIL ") + m, flush=True)
    if not c: raise SystemExit(1)

P1 = {"allow_voice_speedup": True, "max_voice_speedup": 1.6, "min_video_speed": 0.85}
keep, tgt = P.fit_stretch(P1)
ok(abs(keep - 1.6 / 0.85) < 0.01 and 1.5 < tgt < 1.75, f"speed-up + slow-down on: keep {keep:.2f}x, rewrite target {tgt:.2f}x the scene")
ok(P.fit_stretch({"allow_voice_speedup": False, "max_voice_speedup": 1.35}) == (1.0, 0.95), "speed-up off: the old rule (fit at normal speed)")
ok(abs(P.fit_stretch({"allow_voice_speedup": True, "max_voice_speedup": 9, "min_video_speed": 1.0})[0] - P.MAX_SPEEDUP_CAP) < 0.01, "the speed-up is capped (MAX_SPEEDUP_CAP)")
s = P.fit_stretch(P1)
up = 2.5
ok(P._plan(3.2, up, up, lengthen=False, stretch=s) is None and P._plan(4.5, up, up, lengthen=False, stretch=s) is None, "lines 1.28x and 1.8x their scene are kept (voice faster + picture a little slower)")
ok(P._plan(3.2, up, up, lengthen=False) is not None, "...it used to be cut")
mode, t = P._plan(7.0, up, up, lengthen=False, stretch=s)
ok(mode == "shorten" and up * 1.5 < t < up * 1.75, f"a line 2x its scene is cut to {t:.2f}s (not to {up * 0.95:.2f}s)")
ok(P._plan(1.0, up, up, stretch=s) == ("lengthen", up), "a short line is still lengthened")
ok(dm.default_for("standard") == dm.AZURE and dm.default_for("premium") == dm.DEFAULT and dm.default_for(None) == dm.DEFAULT, "default voice timing by quality")
ok(dm.predict("ပွဲဖျက်ဖို့ လုပ်နေတာပါ။", dm.AZURE) > dm.predict("ပွဲဖျက်ဖို့ လုပ်နေတာပါ။", dm.DEFAULT), "Azure predicts longer than the Gemini default")
print("ALL OK")
