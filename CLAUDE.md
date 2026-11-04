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
2. **Transcribe + translate** (`gemini_dub.py`): audio extracted, cut at silences into ~150 s chunks, chunks sent to
   Gemini **in parallel**, JSON with timed segments + Burmese text. Prompt asks for short lines (~10 chars/second).
   Fallback order: provider from `DUB_PROVIDER` -> elevenlabs -> gemini -> local (`local_dub.py`: faster-whisper + NLLB-200;
   slow and weakest Burmese, last resort only).
3. **Voice-over** (`gemini_tts.py`, model `gemini-3.8-flash-tts`, default voice Kore): **one request per sentence**, 8 in parallel.
4. **Fit** (`fit_text.py`): lines whose voice is still too long even after the allowed speed-up are rewritten shorter
   by Gemini (or Claude if `ANTHROPIC_API_KEY`), voice regenerated. On by default.
5. **Sync + render** (`recap_engine.py`): per scene, voice speed-up first (max 1.35x), then video slow-down (min 0.85x),
   then freeze last frame. Captions rendered per sentence. Long videos render in parallel chunks, then are joined.
6. Result files go to storage; the API hands out **signed, expiring URLs**; files are deleted after 24 h.

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
2. **Browser editor (CapCut-like)**: preview of the uploaded video; tracks for video, subtitles, audio clips;
   user can edit subtitle text, trim/move clips, change clip speed. Server returns a "project" JSON
   (segments, times, clip files); the browser plays it with a video element + Web Audio + subtitle overlay;
   export sends the edited project to the server render (browser export only later: heavy, limited browser support).

**Next / backlog**
- Gemini tier upgrade (or Google Cloud TTS / other provider) so volume is possible; confirm real price per video-minute.
- Reach the 3-minute target for 10-min videos: find why parallel render gave no speedup, test on a many-core server,
  measure CPU-seconds per video-second.
- Payments / plans (1,500 THB idea), per-plan daily minutes, admin dashboard, abuse/rate limits behind a gateway.
- Deploy: Docker files exist but are **untested**; HTTPS, Postgres, S3 (Spaces), several workers, monitoring and budget alerts.
- Legal/content: user uploads are third-party footage; terms of service and takedown process.
- Tests: no automated test suite yet; flows were tested by scripts only.

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
