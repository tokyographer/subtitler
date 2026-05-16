# Subtitler

Local macOS video transcription → YouTube-compatible `.srt` subtitle file.

Runs entirely on-device using [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon (M-series). No cloud APIs. No Docker required.

---

## Requirements

| Tool | Version |
|------|---------|
| macOS (Apple Silicon) | Sonoma 14+ recommended |
| Python | 3.11+ |
| Node.js | 18+ |
| FFmpeg | via Homebrew |

---

## Quick Start

### 1. Install FFmpeg

```bash
brew install ffmpeg
```

### 2. Clone / open the project

```bash
cd /path/to/subtitler
```

### 3. Create a Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **First transcription note:** `mlx-whisper` downloads the selected model from
> HuggingFace on first use (e.g. `whisper-large-v3-turbo` is ~1.5 GB). Subsequent
> runs use the local cache at `~/.cache/huggingface/`.

### 5. Start the backend

```bash
uvicorn app.main:app --reload --port 8001
```

### 6. Start the frontend (dev mode)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

### 7. (Optional) Production build

Build the React app into `frontend/dist/`, then FastAPI serves it directly:

```bash
cd frontend
npm run build
cd ..
uvicorn app.main:app --port 8001
```

Open **http://localhost:8001**.

---

## Usage

1. Drag-and-drop (or browse for) a video file.
2. Choose a language (default: auto-detect), model, and engine.
3. Click **Start Transcription**.
4. Watch real-time progress and logs.
5. Click **Download .srt file** when complete.

---

## Configuration

All settings can be overridden with environment variables prefixed `SUBTITLER_`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBTITLER_MAX_FILE_SIZE_MB` | `4096` | Max upload size (MB) |
| `SUBTITLER_DEFAULT_MODEL` | `large-v3-turbo` | Default Whisper model |
| `SUBTITLER_DEFAULT_LANGUAGE` | `auto` | Default language |
| `SUBTITLER_DEFAULT_ENGINE` | `mlx` | Default engine |

Example:

```bash
SUBTITLER_DEFAULT_MODEL=medium uvicorn app.main:app --reload --port 8001
```

---

## Available Models

| Short name | HuggingFace repo | Speed | Quality |
|-----------|-----------------|-------|---------|
| `large-v3-turbo` | `mlx-community/whisper-large-v3-turbo` | Fast | Excellent |
| `large-v3` | `mlx-community/whisper-large-v3-mlx` | Slow | Best |
| `medium` | `mlx-community/whisper-medium-mlx` | Medium | Good |
| `small` | `mlx-community/whisper-small-mlx` | Fast | OK |
| `base` | `mlx-community/whisper-base-mlx` | Very fast | Fair |
| `tiny` | `mlx-community/whisper-tiny-mlx` | Fastest | Low |

---

## Project Structure

```
subtitler/
├── app/
│   ├── main.py              # FastAPI app, routes, background pipeline
│   ├── config.py            # Settings (pydantic-settings)
│   ├── jobs.py              # Thread-safe in-memory job store
│   ├── audio.py             # FFmpeg audio extraction
│   ├── transcribe/
│   │   ├── base.py          # Abstract TranscriptionEngine
│   │   ├── mlx_engine.py    # mlx-whisper implementation
│   │   └── whisper_cpp_engine.py  # whisper.cpp stub (TODO)
│   ├── subtitles/
│   │   └── srt.py           # SRT formatting + line wrapping
│   └── utils/
│       └── files.py         # Upload validation, secure save, cleanup
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main UI component
│   │   ├── api.js           # API helpers + SSE subscription
│   │   └── App.css
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── storage/
│   ├── uploads/             # Temp upload staging (auto-cleaned)
│   ├── audio/               # Extracted WAV (auto-cleaned)
│   └── outputs/             # Generated .srt files (kept)
├── tests/
│   └── test_srt.py          # Unit tests for SRT generation
├── requirements.txt
└── .gitignore
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/upload` | Upload video, start transcription job |
| `GET` | `/api/jobs/{job_id}` | Poll job status + metadata |
| `GET` | `/api/jobs/{job_id}/logs` | SSE stream of logs + progress |
| `GET` | `/api/jobs/{job_id}/download-srt` | Download the finished `.srt` |
| `GET` | `/api/config` | Models, languages, engines, defaults |

### Job states

```
uploaded → extracting_audio → transcribing → generating_srt → completed
                                                             ↘ failed
```

---

## Running Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## Adding a New Language

Edit `app/config.py` → `supported_languages` dict:

```python
"nl": "Dutch",
"pl": "Polish",
```

Any ISO 639-1 code supported by Whisper will work.

---

## Adding whisper.cpp Engine

1. `pip install pywhispercpp`
2. Download a `.bin` model from the [whisper.cpp releases](https://github.com/ggerganov/whisper.cpp/releases).
3. Implement `WhisperCppEngine.transcribe()` in `app/transcribe/whisper_cpp_engine.py`
   (see the docstring in that file for the exact steps).

---

## Security Notes

- File type is validated by magic bytes (not just extension or Content-Type header).
- Uploaded filenames are sanitised to prevent path traversal.
- File size is enforced during streaming — oversized uploads are rejected mid-stream.
- Temporary files (upload + extracted audio) are always cleaned up, even on failure.
- All processing is local; no data leaves the machine.
