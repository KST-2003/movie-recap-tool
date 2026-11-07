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
