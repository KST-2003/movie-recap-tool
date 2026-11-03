# RedNote Video Recap Python Backend

Dubs recap videos (zh/th/my/en -> target language) and keeps audio, video and subtitles in sync.

## Quick Start
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export ELEVENLABS_API_KEY=...        # dubbing + TTS server (node elevenlabs-server.mjs)
export ANTHROPIC_API_KEY=...         # optional: shorten translations that overrun their scene
uvicorn main:app --reload --port 8000
```

System dependencies: `ffmpeg`, plus `libraqm` and `fribidi` so Pillow shapes Burmese correctly
(`brew install fribidi libraqm`; on Debian/Ubuntu `apt install libraqm0 libfribidi0`).

## API
- `POST /api/jobs` (multipart form) -> `{job_id}`; `GET /api/jobs/{id}` -> status, stage, progress, result.
- Output: dubbed MP4 + `.srt`, available under `/api/download/{file}`.

## How sync works (`recap_engine.py`)
Each source scene is retimed to its voice-over: use the silence gap, optionally speed the voice up
(<= 1.15x), else slow the scene's video (>= 0.7x), else hold the last frame. Captions and the `.srt`
come from the final timeline. `subtitle_detect.py` (OCR) finds burned-in subtitles/watermarks so only
those regions are blurred; new captions are drawn where the old ones were.
