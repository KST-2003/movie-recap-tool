# RedNote Recap Studio — project plan & working notes

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
Browser (React/Vite, frontend/)  --HTTPS-->  API (FastAPI, backend/main.py)
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
(revisit if abused; they still cost CPU). Not built yet: merge lines, video thumbnails/waveform on the timeline, undo, voice change in the UI.

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
  `casting.assign_voices`: A (most lines) gets the user's voice if the gender fits, others the next unused voice of their gender (14 female, 16 male);
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
Not done: per-line speaker change re-casts only on re-render; no voice preview per character; emotion quality unverified; Demucs path unchanged/untested here.

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
cd frontend && npm run dev
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
