# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Local macOS app that generates SRT subtitle files from video/audio using on-device Whisper inference. FastAPI backend + Vite/React frontend, dual-engine (mlx-whisper and whisper.cpp), real-time SSE progress streaming.

## Architecture

```
Upload → validate → save to storage/uploads/{job_id}/
       → FFmpeg pipe (no disk WAV) → float32 numpy array
       → engine.transcribe() → list[Segment]
       → segments_to_srt() → storage/outputs/{job_id}/output.srt
```

**Backend layout (`app/`):**
- `main.py` — FastAPI app, 5 routes, SSE streaming, background job dispatch
- `jobs.py` — `Job` dataclass + thread-safe in-memory `JobStore`
- `audio.py` — FFmpeg pipe extraction (16 kHz mono float32, no temp WAV)
- `config.py` — Pydantic Settings with `SUBTITLER_` prefix, loaded from `.env`
- `transcribe/base.py` — Abstract `TranscriptionEngine`, `TranscriptionOptions`, `Segment`
- `transcribe/mlx_engine.py` — mlx-whisper engine (default)
- `transcribe/whisper_cpp_engine.py` — whisper.cpp CLI subprocess engine
- `subtitles/srt.py` — timestamp formatting, line wrapping, segment merging, SRT output
- `utils/files.py` — upload validation (magic bytes via `filetype`), streaming save, cleanup

**Frontend (`frontend/src/`):**
- `App.jsx` — single-component app: drag-drop upload, SSE log tail, progress bar, download
- `api.js` — thin wrappers: `fetchConfig`, `uploadVideo`, `fetchJob`, `subscribeLogs`, `downloadSrtUrl`

**Job lifecycle:** `uploaded` → `extracting_audio` → `transcribing` → `generating_srt` → `completed` / `failed`

**SSE pattern:** `GET /api/jobs/{job_id}/logs` yields events every 100ms; client closes on `"done"` event.

## Run Commands

```bash
# Backend (from project root)
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001

# Frontend (dev, proxies /api → localhost:8001)
cd frontend && npm run dev        # http://localhost:5173

# Frontend (production build)
cd frontend && npm run build      # outputs to frontend/dist/

# Tests
pytest tests/ -v
pytest tests/test_srt.py::TestFormatTimestamp -v  # single class
```

## Configuration

All settings via `SUBTITLER_` env vars (`.env` file, loaded by Pydantic Settings). Key vars:

| Variable | Default | Notes |
|---|---|---|
| `SUBTITLER_DEFAULT_ENGINE` | `mlx` | `mlx` or `whisper_cpp` |
| `SUBTITLER_DEFAULT_MODEL` | `large-v3-turbo` | model key from config mapping |
| `SUBTITLER_DEFAULT_LANGUAGE` | `auto` | or BCP-47 code |
| `SUBTITLER_FFMPEG_HWACCEL` | `true` | VideoToolbox on Apple Silicon |
| `SUBTITLER_HF_CACHE_DIR` | (unset) | custom HuggingFace cache |
| `SUBTITLER_WHISPER_CPP_BINARY` | (unset) | explicit path to `whisper-cli` |
| `SUBTITLER_WHISPER_CPP_MODEL_DIR` | (unset) | GGML model directory |
| `SUBTITLER_WHISPER_CPP_USE_COREML` | `false` | requires `.mlmodelc` bundle |
| `SUBTITLER_MAX_FILE_SIZE_MB` | `4096` | upload size cap |

## Key Patterns & Gotchas

**FFmpeg is piped, not file-based.** `audio.py` writes raw PCM to stdout and reads it into numpy — no temp WAV. Any change here must keep the array shape `(N,)` float32 at 16 kHz.

**Jobs are in-memory only.** `JobStore` is a dict in the FastAPI process. Restarting the server loses all job state. Do not add persistence without updating both `jobs.py` and the SSE streaming logic.

**whisper.cpp engine writes a temp WAV** (in the system temp dir) because the CLI needs a file path. The MLX engine does not.

**Progress callback is rate-limited.** The MLX engine fires a logarithmic ticker (~every 0.5s). Don't remove the sleep/rate-limit or the SSE stream will be overwhelmed.

**File cleanup order matters.** The upload source file is deleted *after* audio extraction but *before* transcription (`cleanup_upload` in `_process_job`). The output SRT is never deleted automatically.

**`filetype` magic-byte check happens at the API boundary** in `validate_upload()` — not in the engine. Extensions alone are not trusted.

**Frontend dev proxy:** Vite proxies `/api/*` to `localhost:8001`. The `api.js` functions use relative paths — don't add an absolute base URL.

## Never Do

- Never write a temp WAV to `storage/` in the MLX path — audio must stay in-memory
- Never expose `srt_path` (absolute server path) in API responses — only serve via the download endpoint
- Never `allow_origins=["*"]` in CORS — already restricted to localhost origins in `main.py`
- Never use `os.path` — always `pathlib.Path`
- Never add state to the FastAPI app instance — state lives in `JobStore`

## Current Status

- MLX engine: production-ready, default
- whisper.cpp engine: fully implemented; Metal + Core ML optional
- Tests: `tests/test_srt.py` covers SRT generation and whisper.cpp helpers; no integration tests yet
- Frontend: single `App.jsx`, no component split yet

## Future Integration

Input: video/audio files from any source (local file, future YouTube downloader stage)
Output: `storage/outputs/{job_id}/output.srt` — consumed by the subtitler-translator module or uploaded directly to YouTube/Bunny Stream
