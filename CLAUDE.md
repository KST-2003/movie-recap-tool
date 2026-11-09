# Movie Recap Tool — project plan & working notes

> **Rule: keep this file up to date.** Whenever a feature is added, a decision is made, a limit is discovered or a
> to-do is finished, update the relevant section below in the same commit. Date entries in the Changelog.

## 1. What we are building
A web app that takes a short "recap" video (Chinese/Thai/English speech, e.g. from RedNote), and produces a copy with:
- the speech transcribed and **translated to Burmese**,
- a **Burmese voice-over** (Gemini TTS) synced to the scenes,
- **Burmese subtitles** (one sentence at a time), original subtitles/watermarks blurred, optional flip/colour/logo.

Target: paid product, ~1,000 users, ~30 min of video/user/day, price idea 1,500 THB/user/month.
Users upload videos up to ~10 min and want results in about 3 minutes (not yet reachable, see §6).

## 2. Architecture (current, branch `feature/google-gemini-dubbing`)
```
Browser (React/Vite, frontend/)  --HTTPS-->  API (FastAPI, backend/main.py)  <--HTTPS--  Owner dashboard (React/Vite, admin/, own sub-domain)
   login, upload, voice picker                 auth, quotas, signed URLs, voice samples
                                                   |  enqueue(job_id)
                                                   v
                                      Redis queue (RQ)  <--  workers (run_worker.sh, 1 job each)
                                                   |
                       backend/pipeline.py  (run_job_by_id)  ->  DB (SQLite dev / Postgres prod)
                                                   |           ->  storage (local disk or S3/Spaces)
```
Without `REDIS_URL` the API runs jobs in an in-process thread pool (dev mode).

### Pipeline for one job (`backend/pipeline.py`)
1. **Subtitle/watermark detection** (`subtitle_detect.py`, RapidOCR on ≤16 sampled frames) -> blur regions.
2. **Scene cuts** (`scene_cuts.py`, ffmpeg, runs alongside step 1) -> cut times go into the Gemini prompt and segment starts/ends
   snap to a cut within 0.3 s. **Transcribe + translate** (`gemini_dub.py`): audio extracted, cut at silences into ~150 s chunks, chunks sent to
   Gemini **in parallel**, JSON with timed segments + Burmese text. Prompt (rewritten 2026-11-07, **untested on real Gemini**): meaning first (no dropped facts/names, complete sentences),
   colloquial recap-storyteller Burmese (`DUB_STYLE_NOTE` overrides the tone), aim ~`BURMESE_CPS` (10) chars/s but allow up to 1.3x,
   split long source sentences instead of cutting meaning, boundaries on pauses/scene cuts, proper punctuation (TTS pauses on it).
   Optional `TTS_STYLE` (delivery instruction before the TTS text, off by default: it may be read aloud) - compare with `test_tts_style.py`. Python computes `cps` per segment and flags `too_long` (> 1.35x CPS); the model is
   not asked for duration/cps fields (it does arithmetic badly).
   Fallback order: provider from `DUB_PROVIDER` -> elevenlabs -> gemini -> local (`local_dub.py`: faster-whisper + NLLB-200;
   slow and weakest Burmese, last resort only).
3. **Voice-over** (`gemini_tts.py`, model `gemini-3.8-flash-tts`, default voice Kore): **one request per sentence**, 8 in parallel.
4. **Fit** (`fit_text.py`, `fit_segments_to_slots`): the SCRIPT is rewritten (Gemini, or Claude if `ANTHROPIC_API_KEY`) until each voice
   line lasts about as long as the original speech (`end - start` from the transcript, capped by the slot): too long -> shortened,
   too short (< `FIT_FILL_RATIO` 0.85 of the speech and >= `FIT_MIN_GAP_SECONDS` 0.5 s of dead air) -> lengthened with faithful
   detail (no new facts); up to 3 rounds, voice regenerated each time. Gaps the source really has are kept. Voice speed-up
   (<= 1.35x) is only the last resort, in the timeline. **Batched for speed (2026-11-07):** a real 169 s video had 64 of 67 lines too long and the old per-line fit (1 LLM + 1 TTS request
   per line per round, 8 at a time) took 5+ minutes at 62%. Now `rewrite_many` sends ~20 lines per LLM request (batches in parallel),
   rewrites are verified with the duration model (bad ones re-asked, text only), accepted ones are voiced together via
   `voice_many` (bulk TTS), max `FIT_ROUNDS`=2 rounds, progress reported. On by default.
5. **Sync + render** (`recap_engine.py`): per scene, voice speed-up first (max 1.35x), then video slow-down (min 0.85x),
   then freeze last frame. Captions rendered per sentence. Long videos render in parallel chunks, then are joined.
6. Result files go to storage; the API hands out **signed, expiring URLs**; files are deleted after 24 h.

### Editor (`Editor.jsx`, `POST /api/jobs/{id}/rerender`)
CapCut-mobile style timeline in SOURCE time: subtitle track (drag a block's left edge = scene boundary, snaps to cuts), voice track
(red = voice longer than its slot), ruler with scene cuts, playhead synced to the result video, tap a block to edit text / voice speed /
delete, "Split" adds a line at the playhead. Browser behaviour not yet verified by hand (build-checked only).
Every finished job stores a `project` (lines with start, text, voice length, slot, output time; subtitle/watermark rects) in
`result`. The editor lets the user edit text, move a line's start (= scene boundary in the source), set a fixed voice speed
(0.7-1.6x, `tempo`) or delete a line; "Apply" creates a **new job** from the same stored source video. Voice clips are cached by
sha1(voice + text) (`storage.put_clip/fetch_clip`), so only changed lines cost a TTS request. Source uploads are now kept for
`FILE_TTL_HOURS` (needed for re-render; s3 needs a bucket lifecycle rule). Re-renders are **not charged** against daily minutes
(revisit if abused; they still cost CPU). Not built yet: merge lines, video thumbnails/waveform on the timeline, undo (voice/character change per line and per character IS built: see "Voices, looks and casting").

### Predicting voice length without the TTS (`duration_model.py`)
duration ~= a x syllables + b (syllables = unstacked, un-killed Myanmar consonants). Measured on real Gemini clips: corr 0.89,
worst error ~0.6 s on ~3 s clips. Fitted per job from its own (text, duration) pairs (defaults 0.13 s/syllable + 0.7 s), stored in
`project.voice_model`, and ported to JS in `Editor.jsx` (live "~X s voice, fits / too long / N s silence" for edited text, estimated
total length; no request). Also used in the fit step: a rewrite is checked by prediction first and re-asked (text-only) up to 2x
before any TTS request is spent; rewrites predicted not to improve are dropped.

### Batched voice requests (`bulk_tts.py`, `TTS_BULK=1`) - splitter fixed 2026-11-07
Real Gemini test (`test_bulk_tts.py`): Gemini does pause 0.3-0.8 s between sentences, but the old "N-1 longest pauses" splitter
failed 2 of 3 runs (3 and 16 sentences). New splitter: candidates = clearly quiet stretches (>=0.12 s, 12 dB below speech); all
boundaries chosen together by dynamic programming so clip lengths match the duration model, rewarding long pauses. Checked offline
on the saved real audio (`bulk_test/*.wav`): 3, 8 and 16 sentences all split; 8-sentence result within 0.03 s of the old good
split; 16-sentence second half lands on the real pauses. If a group is still untrusted it is split in two smaller groups before
falling back to one request per sentence. Edits: unchanged lines come from the clip cache, all changed lines go in one request.
Listened to the 8-sentence cut clips on 2026-11-07: they sound right, so **batching is now ON by default** (`TTS_BULK=0` turns it off).
Still to verify: batches longer than 8 sentences (16 split fine by the numbers, not listened to), voice consistency on a full 10-min job.

### Pre-fit (before any voice)
Real run: 39 of 41 first-pass lines were too long for their scene (Gemini ignores the char budget in the prompt). `prefit_segments`
predicts every line's voice length with `duration_model` and shortens the ones predicted too long in bulk (LLM, ~20 lines per
request, answers verified by prediction) BEFORE the first voice pass, so most lines are voiced once. Lengthening waits for real
lengths (post-voice fit). The uvicorn access log hides the `GET /api/jobs/<id>` polling lines. On restart, jobs left
queued/running by the previous process (inline mode) are marked failed so they stop counting against the active-job limit.

### Time budget (product requirement: a 10-min video must finish in <= 10 min)
Measured floor on an M2 Air with fake Gemini (`python bench_10min.py`): 10-min 720x1280 video = **95 s** total (render 82 s,
subtitle detection 8 s, rest seconds). That leaves ~8 min for Gemini. `run_job` computes `budget = clamp(0.9 x video length, 150,
`JOB_BUDGET_MAX_SECONDS`=540)` and reserves `0.2 x length + 20 s` for the render; pre-fit and each fit round only start if enough
budget is left (otherwise skipped, the timeline speeds up / slows the video instead). The log ends with `finished in Xs ... (budget
Ys)`. Estimate for 10 min (UNVERIFIED with real Gemini): transcribe ~60 s (8 chunks of 75 s, 6 parallel), pre-fit ~30 s, voice ~80 s
(~30 bulk groups, 8 parallel), fit rounds ~100 s, render ~100 s = 6-7 min. Risks: Gemini TTS latency / rate limits under parallel
load, Tier 1 daily request limits (a 10-min video is ~65 Gemini requests), many users at once (needs more workers/cores).

### TTS model pool (`tts_pool.py`)
AI Studio rate limits (Tier 1, per model, seen 2026-11-07): TTS models allow **10 requests/minute and 100/day** (2.5 Pro TTS: 10/min,
50/day); text models ~1,000/day. Every model has its own counters, so the pool multiplies capacity (~450 voice requests/day, ~50/min if
all are used). Models (user's listening test: all acceptable; best 2.5 Flash and 3.1 Flash, then 3.8 Flash; 2.5 Pro sounds a bit off):
`gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-preview-tts`, `gemini-3.8-flash-tts`, `gemini-3.8-flash-lite-tts`,
`gemini-2.5-pro-preview-tts` (order = preference; override `TTS_MODELS="name:rpm:rpd,..."`). The 2.5/3.1 models return bare 24 kHz PCM
without a WAV header (`gemini_tts` adds it). One video uses ONE model (same voice); `Chooser` picks the first model with enough requests
left (by our daily count in `data/tts_usage.json`, Pacific-day reset, and 429 blocks in `data/tts_blocked.json`), keeps a job's model
for edits (`project.tts_model`), and switches mid-video only when a model is exhausted. `acquire()` is a per-model sliding-window limiter
(9/min) used before every request. Uploads are refused only when ALL models are blocked. Counters are per process (RQ workers: split the
share). Bulk groups are now up to 12 sentences / 1800 chars (fewer requests; 16 split fine on real audio; 12 not yet listened to).
Not done: spreading ONE video over several models for speed (voice would change mid-video), fallback text models, Google Cloud TTS.

### Two modes (2026-11-07 night 6)
Upload form: **Recap video** (one narrator voice, as before) or **Full movie / drama** (`mode=full`). Full mode, all untested on real Gemini
(offline-tested with `python test_modes.py`):
- **Translation**: separate prompt (`gemini_dub._prompt_full`, `FULL_TONE`): natural, neutral spoken Burmese, meaning not words, politeness per
  character pair, no literal idioms (user's bad examples ဆင်းရဲတယ် / ဒီလူတွေ / ခွေးလိုရုန်းရ are in the prompt as "don't"). Needs a listening/reading check.
- **Characters**: transcript adds speaker/gender/age/voice-description/emotion per line. Chunks are transcribed in parallel, so labels are per chunk
  ("2:S1"); `unify_speakers` merges them into whole-film characters A, B, ... with ONE text request (fallback: gender+age groups).
  `casting.assign_voices`: A (most lines) gets the user's voice if the gender fits, others a voice chosen by Gemini from the voice tags (one text request), falling back to the age-matched free voice of their gender (14 female, 16 male real voices);
  editor "Characters" panel changes a voice (`speaker_voices` in `/rerender`), only that character is re-voiced (clip cache key = voice+text+style).
- **Voice requests**: `plan_batches` groups lines per voice (bulk), emotional lines go one per request (`EMOTION_MAX_LINES`=12; direction "Say <adverb>: text";
  if the clip is far longer than predicted the direction was read aloud -> line re-voiced plainly). Roughly 15-40 requests per film at 9/min/model.
- **Output**: "Burmese voice-over + subtitles" or "subtitles only" (`output=subtitles`: no TTS, original audio + timing untouched, `plan_source_timing`).
- **Original sound**: `background=original` (default in full mode: source audio under the voice, sidechain-ducked, fast; original speech stays faintly audible),
  `separate` (Demucs, slow, music only), `off`. Recap keeps the old `keep_background` checkbox.
- **Soft tone** (any mode, optional): generated A-minor pad mixed after render (`audio_tools.make_soft_tone/mix_music`); no music licence needed.
- **Caption size**: detection now returns the original subtitle's text-line height; captions = `CAPTION_SIZE_FACTOR` (0.8) x that as font px, because drawn Burmese
  is ~1.45x taller than its font size -> about 15% taller than the original. Measured: 30sec.mov 1080x1920 line 66px -> 53px font; recap.mp4 landscape 55px -> 44px
  (the old fixed 5% of width, 64px, was far too big on landscape). Tune by eye with the env var.
- **Original sound (corrected 2026-11-07 night 7)**: `original` keeps the WHOLE original track lowered, so the original speech stays faintly audible
  (user heard it as "a second voice"). Full-mode default is now `separate` (Demucs `no_vocals` = music + effects, speech removed): 0.43x real time on an M2 Air
  (13 s for 30 s audio, ~3.5-4 min for 8.5 min), runs in a thread beside transcription/voice, waited for at most ~`budget - elapsed - 0.5 x render reserve`; result cached
  as `bgcache_<first job id>.wav` so editor re-renders do not separate again (`bg_source_job` param); on failure/timeout full mode falls back to `original` + a warning.
- **Characters**: a real 508 s run produced 14 characters (mostly 1-3-line ones) = over-splitting. `merge_minor_speakers` folds characters with < 3 lines (and any
  beyond 8) into the same-gender major character speaking closest in time; the merge prompt now prefers merging; editor "merge into..." moves all lines of a
  character to another. Voices are fixed per character ID by `casting`; what can still sound inconsistent: wrong gender/identity labels from Gemini, and
  emotion directions changing the timbre of a styled line.
- **Re-render cost (how it works today)**: a re-render skips detection/transcription/pre-fit/fit, voices only changed lines (clip cache), but ffmpeg re-renders the
  WHOLE video (~50 s parallel for 8.5 min). Idea not built: cache rendered ~40 s windows keyed by their content and re-render only the changed windows.
- **One failure must not fail the film** (action/romance/violence will trigger refusals): (1) transcription: refused chunk -> halves -> skipped part + warning;
  (2) voice: `ContentBlocked` (400 content_blocked, "unspecified policy reason") -> a refused GROUP falls back to single lines; a refused LINE goes down a ladder:
  without emotion direction -> other pool model for that line only -> milder wording (`fit_text.soften`) -> silent clip of the predicted length + warning (`silent`
  lines are not cached/fitted); any other single-line failure after retries is treated the same; if > max(5, 25%) of lines end silent the job fails (service down);
  (3) pre-fit / fit rounds are optional: errors are logged and skipped. Still fatal: cancel, daily quota of ALL models, hard time limit (`JobTooSlow`).
- **Character identity across chunks (2026-11-07 night 9)**: voice drift ("Tom is Kore early, Charon later") came from the same person getting different
  labels in different 75 s chunks, not from the TTS. `SPEAKER_MODE=roster` (default): one whole-film pass (`diarize_full`) lists the characters and turns first; every
  chunk then labels lines with those ids (`apply_diarization(trust_labels=True)`). `SPEAKER_MODE=unify` = old per-chunk labels merged by one text request. Measured on
  samples/recap.mp4 (2 runs each): run-to-run agreement of who-is-who 0.919 roster vs 0.887 unify, +~20 s. `merge_minor_speakers` never merges across genders.
  Not verified by ear on a long film; remaining causes: wrong gender/identity from Gemini, mid-job TTS model switch. Fix by hand in the editor (merge into / voice per character).
- **Blur only where there is something to blur (2026-11-07 night 9)**: the source-subtitle blur is now time-gated. After the band is found, `subtitle_detect.subtitle_windows`
  scans ONLY the band (ffmpeg crop, 1 sample per max(0.5 s, length/700), 8 band images stacked per detector call, detection only): 502 s video = 8.7 s. The windows
  (source seconds, stored in `project.fx.subtitle_windows`, reused by editor re-renders) become an `enable=between(t,..)` on the blur overlay, applied to the SOURCE
  stream before it is cut into scenes (`recap_engine._render_single`, `pre_blur`). Watermark rule tightened (small box <= 45% x 12%, stable text in >= 60% of frames,
  confidence >= 0.8): wide strips of texture were being blurred as "watermarks". `test_blur_windows.py` checks it offline. Not handled: watermarks that jump around.
- **Voice fixes after the real 502 s run (2026-11-07 night 10)**: (1) at 1:59 three lines became a female "character" E: they were the hero reading a system panel, mislabelled
  inside his run. `merge_minor_speakers` now folds a <=3-line character whose every line sits between two lines of the SAME other major character into that character, even across
  genders (`SANDWICH_MERGE=1`; a cameo between two different speakers stays). (2) at 2:42 an emotion direction ("cheerfully") pulled the male voice to another pitch:
  `pitch.py` (numpy F0) compares every emotional clip with the voice's normal pitch (measured once from `voice_samples/<voice>.wav`); outside +-4 semitones the line is re-voiced plainly.
  (3) old man got a young man's voice: casting ignored age. `voices.AGE_VOICES` (male/female x elderly/young/adult, from Google's style words + measured pitch, VERIFY BY EAR) and
  `casting.assign_voices` picks the age-matching free voice (the main character still gets the user's pick); age comes from the roster. Tried and dropped: gender from the SOURCE
  audio's pitch (film music/effects make it unreliable: hero measured 184 Hz). Only 12 of ~70 emotional lines get a direction (cap) - grouping same-emotion lines per request is the open idea.
  Tests: `test_voice_fixes.py`.
Editor (night 10): each character has its own colour (timeline subtitle blocks, badges, line speaker select) and a 🔊 sample button next to its voice.
Editor (night 10c): selected line has one-click character chips (change ONE line's character; the character itself stays), character rows show live line counts, "move all lines to…" shows the chosen target, a hint says changes need Apply. Changing a character/voice always needs a TTS request for the changed lines (other voice = new audio); 
Editor (night 11): "▶ Hear <voice>" on the selected line = `POST /api/jobs/{id}/preview-line` (one TTS request in the character's voice, same emotion style, clip goes into the render cache so Apply does not pay again; 12 previews/min/user). Read-aloud guard tightened (`READ_ALOUD_RATIO` 1.25, `READ_ALOUD_EXTRA` 0.45 s; was 1.5x + 1.0 s, "Say fearfully:" leaked into short lines). Gemini has ONLY the 30 prebuilt voices (14 F / 16 M) on every TTS model; no baby/monster/animal voices exist. `test_voice_styles.py` tries style instructions (baby, old, monster, alien, animal, ghost, robot) -> `character_samples/`; first run: clips 8-13 s for a ~3 s line, so the instruction is probably read aloud or delivery is very slow - LISTEN before building "character looks".
Not done: emotion quality unverified by ear; Demucs path unchanged/untested here (see "Voices, looks and casting" for what is open).

### Voices, looks and casting - state at the end of 2026-11-07 (read this first)
**Voices.** Gemini TTS has only 30 prebuilt voices (14 F / 16 M), identical on every pool model; no baby/monster/animal voices exist. Samples of all 30 are pre-generated in
`backend/voice_samples/` (never regenerated per request; `Cache-Control` 1 week). `voice_tags.json` (committed, hand-editable) = per-voice tags from Gemini LISTENING once
(`generate_voice_tags.py`): gender forced from Google's list (listening got 5/30 wrong), measured F0, Google's style word, age/timbre/energy as heard (unverified, often vague).
**Looks.** 32 looks in `looks.py` (age, creature, machine, animal, mood) = base real voice + performance notes; voice string `look:<id>`; samples in `backend/look_samples/` made by
`generate_look_samples.py` (`--force`, or ids to redo; uses the pool's first model because `gemini-3.8-flash-tts` hung on 2026-11-07). Listen to all 32 and fix weak ones in `looks.py`.
**Prompt format (important).** Old prefix "Say <style>: <text>" was READ ALOUD in English (measured by having Gemini transcribe the clips: looks 7 of 14 s, emotion "fearfully" audible).
Both looks and emotions now use the director's-notes layout (`looks.compose`, `looks.compose_emotion`): English heard = none in the tests (3.8 flash tts only; other models unchecked).
The length guard (`READ_ALOUD_RATIO` 1.25, `READ_ALOUD_EXTRA` 0.45) and the pitch-drift guard (+-4 semitones) remain as safety nets for emotional lines; looks skip both and carry no emotion.
**Casting (full mode).** Roster pass labels characters (gender, age, voice description) -> `merge_minor_speakers` (+ sandwich rule) -> `casting.llm_choice` (ONE text request: characters + 30 voice
lines + the creature/machine/animal/baby looks, which only non-human characters may get) -> `assign_voices` (A keeps the user's pick if gender fits; Gemini's pick for the others if free and gender fits,
else the old `AGE_VOICES` rules). Editor re-renders keep voices. `LLM_CASTING=0` disables the request.
**Editor.** Per-character colours, voice select (Voices + Character looks groups) + sample button, "move all lines to...", per-line character chips, live counts, "Not applied yet" hint, "Apply changes & re-render"
(only changed lines re-voiced), and **"Hear <voice>"** on the selected line (`POST /api/jobs/{id}/preview-line`, 1 TTS request, clip cached for Apply, 12/min/user).
**App UI.** Myanmar/English language switch (`i18n.jsx`, Burmese AI-written, needs native review); upload form shows 4 voices per gender + "See more voices" (`VoiceLibrary.jsx`: search, categories, 30 voices + 32 looks);
mobile fixes (stacked labels, wrapping rows, no horizontal overflow; timeline not checked on a phone). Phone testing: backend `--host 0.0.0.0` with `CORS_ORIGINS`, frontend `VITE_API_BASE=http://<mac-ip>:8000 npm run dev -- --host`.
**Open / unverified.** Nothing above has been run on a real film yet (roster, blur windows, merge rules, casting request, looks); bulk batches of look lines may fall back to single requests; look clips are longer
(slow delivery); looks cannot be the recap-mode voice (upload form picks real voices only); only 12 emotional lines get a direction (cap); no per-voice tags for age beyond what Gemini heard; speaker-embedding clustering
and a character-review step before voicing are still ideas; native review of Burmese UI text.
**Tests** (all offline, run in `backend/` with `venv/bin/python`): `test_admin.py`, `test_google_quota.py`, `test_editor.py`, `test_modes.py`, `test_voice_fixes.py`, `test_blur_windows.py`; real-API scripts: `test_voice_styles.py`, `generate_*`.

### Format + preview before generating (2026-11-07 night 13, format added 2026-11-08)
Like CapCut: the user picks the **format first** (Original, 9:16, 1:1, 4:5, 16:9; "Fit" = whole picture over a blurred copy, "Fill" = crop, drag the picture to pan), then uploads.
`frontend/src/PreviewStudio.jsx` shows the video INSIDE that output frame with live settings (no request): brightness/contrast/saturation (CSS filter, approximates ffmpeg `eq`), video speed (`playbackRate`),
horizontal flip, the uploaded logo as a draggable + corner-resizable overlay (+ size slider, preset corner select), up to 6 draggable/resizable blur boxes (`backdrop-filter`), seek bar, "Play 5 s (loop)".
Form fields: `aspect`, `fit_mode`, `pan_x/pan_y`, `logo_x/logo_y` (fractions of the OUTPUT frame, -1 = preset), `logo_size`, `manual_blurs` (JSON fractions of the output frame, max 6).
Render (`recap_engine._render_single`): order = auto subtitle/watermark blur on the SOURCE -> **reframe** (`EffectOptions.out_size/fit_mode/pan`) -> flip -> manual blur boxes -> grade -> speed -> logo -> captions, so logo/boxes/captions
use output-frame coordinates (no mirroring maths). `pipeline._out_size`: short side = min(1080, source short side) (never upscales), 9:16 from 720x1280 stays 720x1280. Captions go near the bottom when reframed (the
original subtitle position no longer applies); caption font scales with the picture. Checked with a synthetic clip (`render` for 9:16 fit/crop, 1:1, 16:9) + `test_editor.py`.
UNVERIFIED: browser behaviour (touch dragging, blurred-background video sync is approximate), render time of 1080-wide frames vs the 95 s / 10 min floor (measured at 720x1280), auto-detected blur rects not shown in the preview,
manual boxes are not time-limited.

### Finishing settings after the result (2026-11-08)
The four checkboxes (blur original subtitles, Burmese subtitles, blur lower-right watermark, horizontal flip) are NOT in the upload form any more: first render uses
blur subtitles ON, Burmese subtitles ON, watermark blur OFF, flip OFF; the editor has a "Look & sound" box with them (+ "Original music & effects volume" slider when the result kept the film's sound)
and "Apply changes & re-render" sends them (`/rerender` body: `blur_subtitles, enable_subtitles, remove_watermark, enable_flip, bg_volume`, all optional, copied into the new job's params).
Why watermark blur defaults OFF: it is a FIXED box (25% x 12%, bottom-right of the SOURCE picture, `recap_engine`), applied before flip, so with flip it showed up bottom-LEFT of results (looked like a stray blur).
**Output choice** (voice-over + subtitles | subtitles only, original sound stays) is now shown in BOTH Recap and Full modes (backend already allowed it; `test_modes.py` covers recap + subtitles).
**Original sound level**: separated music/effects used to be mixed at 0.35 (and 0.5 ducked) with sidechain ratio 12 = effects (thunder) too quiet. Now default 0.8 (0.7 when the whole original track is kept under the voice),
ratio 4, user slider `bg_volume` 0-1.5. Known limit: Demucs `no_vocals` treats screams/ghost voices as vocals and removes them (use "Keep everything, lowered" to keep those, original speech then stays faintly audible).

### Admin dashboard (2026-11-09, branch `feature/admin-dashboard`) - a SEPARATE app: `admin/`
Three top-level folders: `backend/` (API), `frontend/` (the user app, port 3000), **`admin/` (owner dashboard, own Vite app, dev port 3001, deployed on its own sub-domain, e.g. admin.example.com)**.
Details for running/deploying: `admin/README.md`. Both browser apps call the same API; the backend must allow both origins (`CORS_ORIGINS=https://app...,https://admin...`; dev defaults include :3000 and :3001, checked with a real preflight).
**Backend** `backend/admin/` (package: `routes.py` = router `/api/admin/*`, `settings.py` = runtime settings, `google_quota.py`; `main.py` includes the router). Every route needs `is_admin` (`python manage.py create-user EMAIL PASSWORD --admin`).
Routes: `overview` (counts, queue, minutes today, 14-day series), `users` (search, paging, create, PATCH daily minutes / enable / admin / password reset; you cannot disable or demote yourself), `jobs` (filter by status or user,
cancel any job), `tts` (see below), `google-quota` (raw Google rows), `settings` (GET/PUT), `audit` (list, filter by action). `settings.py`: maintenance mode and the global daily ceiling are changeable at runtime
(file `data/admin_settings.json`, falls back to `.env`); `main.py` reads them per request. `/api/auth/login|register|me` return `is_admin` (`me` also `id`).
**Audit log:** table `audit_log` (`db.AuditLog`, created by `create_all`, no migration): one row per SUCCESSFUL admin change, same transaction as the change: `user.create`, `user.update` (per-field `{from, to}`; a password
change is only `password_reset: true`), `job.cancel`, `settings.update` (only fields that really changed). Refused actions write nothing. Not logged: logins, reads, user-side actions.
**Admin app** (`admin/`): own sign-in (`src/App.jsx`, token under its own localStorage key, refuses non-admin accounts), shell `Admin.jsx` (sidebar / phone drawer, log out, optional "Open app" link `VITE_APP_URL`), one `*Page.jsx` per page,
`ui.jsx` shared pieces + `useApi`, `i18n.jsx` + `strings.js` Myanmar/English (AI-written Burmese, needs native review; new texts need an entry in `strings.js`). Env: `VITE_API_BASE`, `VITE_APP_URL` (`admin/.env.example`). URL hash = page (`#users`).
Mobile: tables become cards, forms bottom sheets, filter chips scroll sideways. Charts are plain divs. Built in our own Tailwind style (Flatlogic react-dashboard was only a layout idea; no LICENSE file there, no code copied).
**Voice models page = three layers per model:** (1) what we configured (`TTS_MODELS`) and counted (`tts_usage.json`); (2) **Google's own words**: `gemini_tts.learn_limit` stores the limit named in every 429 error ("limit: 100 ... per day") in
`data/tts_limits_seen.json`; plus `models.list` with the API key proves the model exists for the key and gives token limits (no quota fields exist there, checked); (3) **real limits + usage from Google Cloud** (`google_quota.py`):
Service Usage API `consumerQuotaMetrics` (effectiveLimit per bucket) + Cloud Monitoring `serviceruntime.googleapis.com/quota/rate/net_usage` since Pacific midnight. Needs `GCP_PROJECT_ID` + `GCP_SERVICE_ACCOUNT_FILE` (service account with
"Service Usage Viewer" + "Monitoring Viewer", both APIs enabled; steps in `backend/.env.example`; key file stays outside git). Cached (models/limits 10 min, usage 60 s), a failing half shows its error next to the half that worked.
The page warns when Google's limit differs from the configured one. UNVERIFIED against real Google Cloud (needs the user's credentials): Google does not document the metric labels of the Gemini API, so models are matched by name appearing in quota
dimensions/labels and request quotas are recognised by "request" in the metric name; the page's "Show what Google returns" panel lists the raw rows to tune this. Several matching limits (free + paid tier) = biggest shown, flagged.
Tested offline with canned Google answers: `python test_admin.py` (38 checks), `python test_google_quota.py` (23 checks), `npm run build` in `admin/` and `frontend/`, scope check for undefined names, Burmese key coverage.
NOT verified: the admin UI in a browser (Chrome extension was not connected), phone layout by eye. Not built: logging of logins / failed admin attempts, per-user job history beyond the Jobs filter, deleting users, payments/plans.

### Allowances, sidebar and usage dashboard (2026-11-09)
Limits per user: **100 min/day and 2000 min/month** (UTC day / calendar month). `User.monthly_minutes` (+ migration in `db.py` for old databases), `DEFAULT_DAILY_MINUTES`=100, `DEFAULT_MONTHLY_MINUTES`=2000.
Upload is refused (402) when either is exceeded; `remaining_seconds` in `/api/auth/me` = the smaller of the two. Re-renders stay free (charged_seconds 0). Failed/cancelled jobs are refunded (so they count for neither).
`GET /api/usage` (the user's own): daily/monthly used, 30 days of minutes, minutes by type (recap / full / subtitles), recent 20 videos, reset times. `manage.py set-monthly`, `create-user --monthly`.
Admin (separate `admin/` app): Users page shows month usage and edits monthly minutes (audit log knows the field).
Main app (`frontend/src/Shell.jsx`): **sidebar** (Create video | My usage, today/month meters, account, language, log out); on phones a top bar with a hamburger toggle opens it as a drawer.
`UsageDashboard.jsx`: two allowance cards, stat tiles, 30-day bar chart (one series, tap/hover tooltip, "Show table"), by-type bars, recent videos. Create page stays mounted while the usage page is open.
UNVERIFIED in a browser (the Chrome extension was not connected): layout of sidebar/drawer/dashboard, chart hover. API + limit enforcement were tested with TestClient.
Cost note (estimates, not measured): ~0.55-0.8 THB per video-minute -> 2000 min/month costs 1,100-1,600 THB at the cap. Idea not built: log real tokens/voice-seconds per job to show true cost per minute.

### Progress UI
The source video previews as soon as a file is chosen; on Generate the player shows a spinner overlay + Cancel and a step
checklist (upload %, subtitles/cuts, translate, voice, fit, render) with the live stage text and an elapsed timer. Backend progress:
3 detect, 10 translate, 35-60 voice, 62-67 fit, 68 timeline, 75-100 render. Transcription chunks are now 75 s (`GEMINI_DUB_CHUNK_SECONDS`)
so long videos are translated in parallel pieces (a 169 s video took 46 s as one chunk).

### Cancel
`POST /api/jobs/{id}/cancel` sets status `cancelled` (nothing charged). The worker stops at its next step (`check_cancelled` in
voice/fit loops, `set_job` raises `JobCancelled`); a cancelled queued job is skipped. A call already running at Gemini/ffmpeg finishes
first. UI: spinner overlay on the preview, editor dimmed + disabled, Cancel button; the old result stays.

### Queue wait
Queued jobs report `queue_position` and `eta_seconds` = (jobs ahead - free workers + 1) x average recent run time / `QUEUE_WORKERS`
(set it to the number of worker processes; default = `RECAP_WORKERS` = 2). The UI shows "Waiting in line: you are #N, about M min".

### Other modules
- `auth.py`/`db.py`/`config.py`: accounts (scrypt + JWT), `users`/`jobs` tables, all limits from env (see `backend/.env.example`).
- `storage.py`: local or S3-compatible. `jobs_queue.py`: RQ or inline. `manage.py`: admin CLI (create users, set minutes).
- `voices.py` + `generate_voice_samples.py`: 30 Gemini voices, pre-generated samples (free preview in the UI).
- `TTS_PROVIDER=fake` writes a tone instead of calling Gemini: use for tests and load tests.

## 3. How to run locally
```
cd backend && source venv/bin/activate && uvicorn main:app --port 8000      # restart after every backend change
cd frontend && npm run dev      # http://localhost:3000
cd admin && cp .env.example .env && npm install && npm run dev      # http://localhost:3001 (owner dashboard, needs an --admin account)
# queue mode: redis-server &  REDIS_URL=redis://localhost:6379 uvicorn ... ; REDIS_URL=... ./run_worker.sh
```
Keys live in `backend/.env` (git-ignored). Admin: `python manage.py create-user EMAIL PASSWORD --minutes 30`.

## 4. Done so far
- Replaced ElevenLabs Dubbing with Gemini for transcribe/translate (ElevenLabs credits ran out: one 6 s video cost 1,289 credits).
- Gemini TTS voice (sounds right in Burmese), 30-voice picker with play/download samples.
- Sentence-by-sentence subtitles; sync tuned (voice speed-up 1.35x, video >= 0.85x); Gemini timing hint in the prompt.
- Speed work: parallel TTS/fit, parallel chunked transcription, Gemini "thinking" off, parallel chunked render.
- Production foundations: accounts, daily minute quotas, queue + workers, DB, S3-capable storage, signed URLs, file expiry,
  CORS list, upload/length limits, kill switch (`MAINTENANCE_MODE`), global daily ceiling.
- Tested: auth, quotas, inline + Redis queue with a separate worker, signed URLs (with fake TTS).

## 5. Known limits & lessons (read before changing things)
- **Gemini TTS Tier 1 = 100 requests/day** (error text: "limit: 100 requests per day on Tier 1"). One 10-min video needs ~140
  sentence requests, so Tier 1 cannot serve even one full video/day. Need a higher tier, fewer requests, or another TTS.
- The Gemini SDK silently retries 429s (even "retry in 16h"), which looks like a hang. We set `retry_options attempts=1`
  and retry ourselves; daily-quota errors fail fast.
- Free AI Studio tier is tiny (20 text requests/day, 10 TTS/day). Billing is enabled (paid tier 1 as of 2026-11).
- ElevenLabs Dubbing is accurate but expensive per video and its voice sounded odd; kept only as a fallback.
- Local NLLB translation is poor for Burmese (meaning errors) and slow on CPU (loads ~3 GB of models).
- `gemini-2.5-flash` is closed to new users; current text model is `gemini-3.8-flash`. `thinking_budget=0` is ~4x faster.
- Render on an M2 Air: ~50 s for 170 s of output; parallel chunk render gave almost no gain on this laptop
  (reason not found; may differ on a many-core server).
- Gemini TTS price (third-party figures, unverified): ~$9 / 1M audio tokens, ~1.4 cents per minute of speech, possibly
  doubling 2027-01-01. Voice cost ~ $12 per user per month at 30 min/day.
- Capacity (estimate): 30,000 video-min/day needs roughly 10–20 cores busy on average, 40–80 at peak. A 2 vCPU / 4 GB
  droplet is for a small beta only. Disable local models and Demucs on servers.

## 6. To do / roadmap
**In progress — branch `feature/bulk-voice-editor`**
1. **Large TTS requests.** Built (`backend/bulk_tts.py`, enabled with `TTS_BULK=1`, off by default): up to 8 sentences /
   1,200 chars per request, sentences separated by a blank line; the audio is cut back into one clip per sentence at the
   N-1 longest pauses; if the split looks wrong (too few pauses, clip lengths far from text length) that group falls back
   to one request per sentence. Tested offline with `TTS_PROVIDER=fake` only (splitter + full job).
   **Still to do:** run `python test_bulk_tts.py` against real Gemini once the daily TTS quota is free (it was exhausted on
   2026-11-04/05): check max input length, voice consistency, whether Gemini really pauses between sentences, and tune
   `TTS_BULK_*` settings. Then decide whether to turn it on by default.
2. **Browser editor (CapCut-like)**: **v1 built** (line list: text, start, voice speed, delete, re-render; see Editor above;
   tested offline with `python test_editor.py`, browser UI only build-checked, not clicked through yet). Next: video
   thumbnails + waveform, merge, undo, live preview without re-render (video + Web Audio + caption overlay).

**Next / backlog**
- Gemini tier upgrade (or Google Cloud TTS / other provider) so volume is possible; confirm real price per video-minute.
- Reach the 3-minute target for 10-min videos: find why parallel render gave no speedup, test on a many-core server,
  measure CPU-seconds per video-second.
- Payments / plans (1,500 THB idea), per-plan daily minutes, admin dashboard, abuse/rate limits behind a gateway.
- Deploy: Docker files exist but are **untested**; HTTPS, Postgres, S3 (Spaces), several workers, monitoring and budget alerts.
- Legal/content: user uploads are third-party footage; terms of service and takedown process.
- Tests: no automated test suite; scripts only (`test_editor.py` offline end-to-end for cuts + editor + queue ETA; `test_bulk_tts.py`).
- Scene-cut prompt/snapping and the 10-concurrent-jobs plan (10 workers, 10-20 cores, ~1 h worst-case wait for 100 simultaneous
  submissions) are untested against real Gemini / real load. Also pending: bigger TTS chunks (30-60 s) instead of 8 sentences.

## 7. Conventions
- Work on feature branches; commit messages end with the Co-Authored-By line.
- Backend changes need a uvicorn restart (we do not run `--reload`).
- Never commit `.env`, `data/`, uploads/outputs, voice sample `.wav` files.

## 8. Changelog
- 2026-11-03: new branch `feature/google-gemini-dubbing`; Gemini replaces ElevenLabs for dubbing; `.env` loading.
- 2026-11-04: voice picker + samples, sentence subtitles, sync tuning, speed work, accounts/queue/storage architecture;
  discovered Gemini TTS Tier 1 limit (100 requests/day).
- 2026-11-05: branch `feature/bulk-voice-editor` created from the Gemini branch; this file added; `bulk_tts.py`
  (batched voice requests, fake-voice tested) and `test_bulk_tts.py` added. Real Gemini test pending quota reset.
- 2026-11-07: scene-cut detection + new Gemini prompt (punctuation, scene-aware boundaries, cps flagging); editor v1 with
  re-render endpoint and voice-clip cache; queue position/ETA; CORS defaults include 127.0.0.1; `test_editor.py`.
- 2026-11-07 (later): two-sided script fitting (lengthen short lines / shorten long ones, speed last), cancel for jobs and
  re-renders, loading overlay + disabled editor while re-rendering, Gemini prompt rewritten for meaning + recap tone.
- 2026-11-07 (evening): duration prediction model (backend + editor), prediction-guided bulk splitter (real-audio tested), edits voiced in
  one request, halving fallback for untrusted bulk groups.
- 2026-11-07 (night): bulk voice requests ON by default after listening test.
- 2026-11-07 (late): batched fit rewrites + bulk voice for rewrites (was minutes at 62%), 75 s transcription chunks, instant preview +
  step checklist + elapsed timer + upload progress.
- 2026-11-07 (night 2): pre-fit shortening before voice, TTS timeout 60 s + visible retries, orphaned jobs cleaned on startup, quiet polling logs.
- 2026-11-07 (night 3): time budget + skip of optional fitting, bench_10min.py (local floor 95 s for 10 min), LLM rewrite parallelism 8.
- 2026-11-07 (night 4): hard job limit (`JOB_HARD_LIMIT_SECONDS`=720, fails cleanly, refunded), no silent ElevenLabs/local fallback unless
  `DUB_FALLBACK=1`, second LLM ask skipped when budget is low.
- 2026-11-07 (night 5): TTS model pool with per-minute limiter and daily counters, 5 models, per-model blocks, WAV header fix; samples/ folder
  for test videos; test_tts_models.py.
- 2026-11-07 (night 6): Recap/Full modes, characters with fixed voices, emotions, subtitles-only, original sound ducked, soft tone, caption size from the
  original subtitle; empty/timed-out Gemini answers retried (text client timeout 180 s). Real 502 s video finished in 369 s (budget 452 s).
- 2026-11-07 (night 7): full-mode default original sound = speech removed (Demucs, cached, time-limited, fallback); minor-character merge + editor merge control;
  Gemini refusals split/skipped; vertical flip removed from the UI. Real full-mode run: 508 s video in 380 s.
- 2026-11-07 (night 8): voice content_blocked ladder + silent-line fallback, optional steps can't fail the job, `JobTooSlow` stays fatal.
- 2026-11-07 (night 9): whole-film speaker roster pass for stable character voices; app language setting Myanmar/English (`frontend/src/i18n.jsx`: `tr()` for UI text,
  `trs()` for server texts via regex table; choice kept in localStorage; Burmese wording AI-written, needs native review; new UI strings must be added to `MY` there).
- 2026-11-07 (night 9b): subtitle blur only while the source subtitle is on screen; stricter watermark detection (no more blurred empty corners).
- 2026-11-07 (night 10): mislabel merge (system-panel lines no longer a female character), emotion pitch-drift guard, age-aware voice casting.
- 2026-11-07 (night 10b): editor: colour per character on the timeline, voice sample button per character.
- 2026-11-07 (night 10c): editor: per-line character chips, live counts, move-all select value, apply hint.
- 2026-11-07 (night 11): per-line voice preview (endpoint + editor button), tighter read-aloud guard, `test_voice_styles.py` (character looks experiment).
- 2026-11-07 (night 11b): character looks catalogue (`backend/looks.py`, 32 looks: baby/child/teen/old/wise, monster/giant/demon/dragon/goblin/zombie/ghost/witch/fairy, alien/robot/AI, cat/dog/small animal/bird/fox/bear, villain/hero/whisper/drunk/sleepy/announcer = base Gemini voice + "Say in a ... voice:" instruction). `python generate_look_samples.py` makes `look_samples/<id>.wav` (skips existing, ~1 request each); `GET /api/looks`, `/api/look-samples/{id}.wav`; the upload form has a "Character looks" section with play buttons. User judged the first test samples acceptable. NOT built yet: choosing a look for a character (would be voice + instruction in the clip key, read-aloud check must allow the instruction, pitch-drift guard must be off for looks) and mobile check of the timeline.
- 2026-11-07 (night 11c): voice picker shows 4 voices per gender (+ the chosen one) and a "See more voices" button -> `VoiceLibrary.jsx` full-screen page: all 30 Gemini voices + character looks, category chips (all/female/male/age/creature/machine/animal/mood), search box, play/download, "Use" for real voices (looks are sample-only until character looks can be chosen).
- 2026-11-07 (night 12): **Gemini voice matching.** `generate_voice_tags.py` (one-time, 30 text requests, audio input) let Gemini listen to each real-voice sample -> `backend/voice_tags.json` (committed; edit by hand to fix). Listening was wrong on gender for 5/30 voices (Kore, Aoede, Laomedeia, Pulcherrima, Vindemiatrix tagged male) and its age words never say "elderly", so `voice_tags.fix` overrides gender with Google's list, adds measured F0 (`pitch.py`) and Google's one-word style (from memory, check); timbre/age/energy are as heard (unverified, sometimes contradicting, e.g. Kore "deep"). Per film `casting.llm_choice` = ONE text request (`voice_tags.cast`: characters' gender/age/voice description + 30 voice lines -> one voice each); `assign_voices(..., suggested)` uses it for every character except A (A keeps the user's voice if the gender fits), ignores picks of the wrong gender / already used voices; any failure -> the old `AGE_VOICES` rules. Editor re-renders do not ask again (they keep each character's voice). `LLM_CASTING=0` turns it off. Looks (voice + instruction) are NOT castable yet. Test: `test_voice_fixes.py`.
- 2026-11-07 (night 12b): **Character looks are castable.** A look = voice string `look:<id>` (e.g. `look:monster`) = base real voice + performance notes (`looks.py`: `is_look/valid/resolve/gender_of/compose`). `pipeline.synthesize` resolves it (base voice + `looks.compose`), emotion directions are dropped for look lines (`voice_many`, emotion candidates skip them), the clip cache key already differs (voice string), last ladder step falls back to the plain base voice if the look's wording is refused. Editor: voice select has "Voices" + "Character looks" groups, sample button works for looks; `/rerender` `speaker_voices` and `/preview-line` accept looks. Gemini casting may pick `look:` only for creature/machine/animal groups + baby (`looks.AUTO_IDS`), only when the description says so. **Measured: the old prefix "Say in a deep growling monster voice: <text>" was READ ALOUD in English (7 of 14 s)** (found by letting Gemini transcribe the clip) -> looks now use the director's-notes layout ("### DIRECTOR'S NOTES / Style: ... Do not read these notes aloud. / #### TRANSCRIPT / text"); 3 layouts (bracket, notes, profile) had no English heard. Look samples were regenerated in the new format. Unverified: bulk batches of look lines (slower delivery may make the splitter fall back to single requests), look clip lengths (slow voices are longer), other pool models than 3.8 flash tts.
- 2026-11-07 (night 12c): emotion directions use the same director's-notes layout (`looks.compose_emotion`): measured with Gemini transcribing the clip, "Say fearfully: <Burmese>" had English heard (4.9 s), the notes layout none (3.6 s). This was the user's "Say fearfully" in the audio bug. Read-aloud length guard stays as a second net.
- 2026-11-07 (night 12d): CLAUDE.md consolidated (section "Voices, looks and casting"); look sample generator hardened (pool model, redo by id).
- 2026-11-07 (night 13): preview studio before generating (live grading/speed/flip, draggable logo, blur boxes, 5 s loop); backend `logo_x/logo_y/manual_blurs`.
- 2026-11-08: video format picker before upload (9:16, 1:1, 4:5, 16:9; fit with blurred background or fill/crop with pan), preview shows the output frame; logo corner resize; app renamed Movie Recap Tool.
- 2026-11-08 (b): form checkboxes moved to the editor (Look & sound), watermark blur + flip default off, subtitles-only offered in recap mode too, louder/gentler-ducked original effects + volume slider.
- 2026-11-09: admin dashboard as a separate app `admin/` (own sub-domain, own login, Myanmar + English): overview, users, jobs, voice models, audit log, runtime settings; backend package `backend/admin/`. Voice models page shows our counters + Google's own limit words (learned from 429s) + `models.list` check + real limits/usage via Service Usage/Cloud Monitoring (needs GCP service account; unverified with real credentials).

- 2026-11-09: monthly allowance (2000/month, 100/day), `/api/usage`, sidebar + usage dashboard in the main app, monthly minutes in admin.
