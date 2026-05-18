# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Local macOS app that generates SRT subtitle files and readable transcripts from video/audio using on-device Whisper inference. FastAPI backend + Vite/React frontend, dual-engine (mlx-whisper and whisper.cpp), real-time SSE progress streaming, Claude API transcript reconstruction.

## Architecture

```
Upload → validate → save to storage/uploads/{job_id}/
       → FFmpeg pipe (no disk WAV) → float32 numpy array
       → engine.transcribe() → list[Segment]
       → detect_loop() → raw_transcript.srt (always)
                       → safe_transcript.srt + postprocess_report.json (if loop detected)
       → [optional] strip_translation_segments() → filtered_transcript.srt
       → srt_path = best available SRT
       → [optional] reconstruct_transcript() → transcript.md (Claude API)
```

**Backend layout (`app/`):**
- `main.py` — FastAPI app, 8 routes, SSE streaming, background job pipeline
- `jobs.py` — `Job` dataclass + thread-safe `JobStore`; fields: `srt_path`, `raw_srt_path`, `safe_srt_path`, `loop_info`, `transcript_path`, `transcript_status`
- `audio.py` — FFmpeg pipe → 16 kHz mono float32 numpy array (no temp WAV)
- `config.py` — Pydantic Settings with `SUBTITLER_` prefix
- `transcript.py` — Claude API transcript reconstruction with prompt caching
- `transcribe/base.py` — Abstract `TranscriptionEngine`, `TranscriptionOptions`, `Segment`
- `transcribe/mlx_engine.py` — mlx-whisper engine; temperature tuple `(0.0, 0.2, …, 1.0)` enables fallback; `is_model_cached()` checks HF cache
- `transcribe/whisper_cpp_engine.py` — whisper.cpp CLI subprocess engine
- `transcribe/postprocess.py` — `detect_loop()` (two-factor: run ≥ 20 AND fraction ≥ 10%); `strip_translation_segments()` (explicit opt-in only); `LoopInfo` dataclass
- `subtitles/srt.py` — timestamp formatting, line wrapping, segment merging, SRT output
- `utils/files.py` — upload validation (magic bytes via `filetype`), streaming save, cleanup

**Frontend (`frontend/src/`):**
- `App.jsx` — single-component UI: drag-drop, SSE log tail, progress bar, hallucination warning table, download buttons (safe SRT + raw SRT), transcript generate/download
- `api.js` — `fetchConfig`, `uploadVideo`, `fetchJob`, `subscribeLogs`, `downloadSrtUrl`, `downloadRawSrtUrl`, `generateTranscript`, `downloadTranscriptUrl`

**Job lifecycle:** `uploaded` → `extracting_audio` → `transcribing` → `generating_srt` → `completed` / `failed`

**SSE pattern:** `GET /api/jobs/{job_id}/logs` yields events every 100ms. `done` event includes `hallucination_warning`, `segments_dropped`, `loop_info`. Client closes on `done`.

## Run Commands

```bash
# Backend (from project root)
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001

# Frontend (dev, proxies /api → localhost:8001)
cd frontend && npm run dev        # http://localhost:5173

# Frontend (production build, served by backend)
cd frontend && npm run build      # outputs to frontend/dist/

# Tests
pytest tests/ -v
pytest tests/test_postprocess.py::TestDetectLoop -v  # single class
```

## Configuration

All settings via `SUBTITLER_` env vars (`.env` file, Pydantic Settings). Key vars:

| Variable | Default | Notes |
|---|---|---|
| `SUBTITLER_ANTHROPIC_API_KEY` | (unset) | Required for transcript generation |
| `SUBTITLER_TRANSCRIPT_MODEL` | `claude-sonnet-4-6` | Claude model for reconstruction |
| `SUBTITLER_DEFAULT_ENGINE` | `mlx` | `mlx` or `whisper_cpp` |
| `SUBTITLER_DEFAULT_MODEL` | `large-v3-turbo` | model key from `mlx_model_repos` |
| `SUBTITLER_DEFAULT_LANGUAGE` | `auto` | BCP-47 code or `auto` |
| `SUBTITLER_FFMPEG_HWACCEL` | `true` | VideoToolbox on Apple Silicon |
| `SUBTITLER_HF_CACHE_DIR` | (unset) | custom HuggingFace cache path |
| `SUBTITLER_WHISPER_CPP_BINARY` | (unset) | explicit path to `whisper-cli` |
| `SUBTITLER_WHISPER_CPP_MODEL_DIR` | (unset) | GGML `.bin` model directory |
| `SUBTITLER_WHISPER_CPP_USE_COREML` | `false` | requires `.mlmodelc` bundle |
| `SUBTITLER_MAX_FILE_SIZE_MB` | `4096` | upload size cap |
| `SUBTITLER_REPETITION_LOOP_MAX_RUN` | `20` | min consecutive identical segments to flag |
| `SUBTITLER_REPETITION_LOOP_MIN_FRACTION` | `0.10` | min fraction of total segments to flag |

## Key Patterns & Gotchas

**focus_language is a Whisper decoding hint, not a content filter.** Do not use it to discard segments in other languages. `strip_translation_segments()` is the explicit content filter and must only run when `filter_translation_track=True` is passed by the user.

**detect_loop() never discards data.** It returns `(clean_segments, loop_segments, loop_info)`. Both lists together equal the full original list. `raw_transcript.srt` is always written from all segments. Never truncate silently.

**Two-factor loop detection.** A run is only a hallucination if it has ≥ 20 consecutive identical segments AND those segments represent ≥ 10% of the total. Raising only `max_run` without the fraction guard causes false positives on short conversational repetition ("Right, right, right…").

**condition_on_previous_text=False by default.** This prevents hallucination cascades where one bad segment primes the next. Reverting to `True` re-enables cascades on long multilingual audio.

**Temperature is a tuple, not a scalar.** `mlx_engine.py` passes `(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)` when `options.temperature == 0.0`. A scalar `0.0` disables Whisper's fallback recovery mechanism.

**FFmpeg is piped, not file-based.** `audio.py` writes raw PCM to stdout and reads it into numpy — no temp WAV. Array shape must stay `(N,)` float32 at 16 kHz.

**Jobs are in-memory only.** `JobStore` is a dict in the FastAPI process. Restarting the server loses all job state.

**whisper.cpp engine writes a temp WAV** (system temp dir) because the CLI needs a file path. The MLX engine does not.

**Progress callback is rate-limited.** The MLX engine fires a logarithmic ticker (~every 0.5s). Do not remove it.

**File cleanup order:** upload file deleted after audio extraction, before transcription. Output SRTs are never deleted automatically.

**`filetype` magic-byte check at API boundary** in `validate_upload()`. Extensions alone are not trusted.

**Frontend dev proxy:** Vite proxies `/api/*` to `localhost:8001`. Keep `api.js` using relative paths.

**SRT output files:** `srt_path` on the Job always points to the best available SRT (safe if loop detected, raw otherwise). Never read `srt_path` from the API response — it is an absolute server path and is not exposed. Download via the endpoint only.

## API Routes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/upload` | Upload + start transcription |
| `GET` | `/api/jobs/{id}` | Job metadata |
| `GET` | `/api/jobs/{id}/logs` | SSE stream |
| `GET` | `/api/jobs/{id}/download-srt` | Best SRT (safe if loop, raw otherwise) |
| `GET` | `/api/jobs/{id}/download-raw-srt` | Raw SRT (always, includes loop) |
| `POST` | `/api/jobs/{id}/transcript` | Start transcript generation |
| `GET` | `/api/jobs/{id}/download-transcript` | Download `.md` transcript |
| `GET` | `/api/config` | Models, languages, engines, defaults |

## Never Do

- Never write a temp WAV to `storage/` in the MLX path — audio must stay in-memory
- Never expose `srt_path` (absolute server path) in API responses
- Never `allow_origins=["*"]` in CORS
- Never use `os.path` — always `pathlib.Path`
- Never add state to the FastAPI app instance — state lives in `JobStore`
- Never call `strip_translation_segments()` automatically — it is an explicit user opt-in
- Never discard loop segments — always preserve them in `raw_transcript.srt`
- Never pass `temperature=0.0` as a scalar to mlx-whisper — use the tuple form

## Tests

69 tests across two files:

- `tests/test_srt.py` — SRT generation, timestamp formatting, line wrapping, merge gap, whisper.cpp helpers
- `tests/test_postprocess.py` — loop detection (both old and new API), multilingual preservation, no-discard guarantee, LoopInfo accuracy, translation filter isolation

Run before committing any changes to `postprocess.py`, `srt.py`, or `mlx_engine.py`.

## Current Status

- MLX engine: production-ready, default
- whisper.cpp engine: fully implemented; Metal + Core ML optional
- Transcript generation: working; requires `SUBTITLER_ANTHROPIC_API_KEY`
- Hallucination detection: two-factor guard (run ≥ 20 AND fraction ≥ 10%)
- Frontend: single `App.jsx`, no component split
- No integration tests yet (transcription requires real audio + model)

## Future Integration

Input: video/audio from any source (local file, future YouTube downloader stage)
Output: `storage/outputs/{job_id}/raw_transcript.srt` and `transcript.md` — consumed by the subtitler-translator module or uploaded directly to YouTube/Bunny Stream
