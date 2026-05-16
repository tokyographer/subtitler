# Subtitler

Local macOS transcription app that turns media files into YouTube-compatible `.srt` subtitles.

Runs fully on-device on Apple Silicon using `mlx-whisper`.
No cloud APIs. No Docker required.

---

## Features

- FastAPI backend with background transcription jobs
- React + Vite frontend with drag-and-drop upload
- Live progress and logs via Server-Sent Events (SSE)
- YouTube-compatible SRT timestamp formatting
- Local-only processing (media never leaves your machine)
- File validation by extension and magic bytes
- Automatic cleanup of temporary upload/audio files

---

## Current Engine Status

- `mlx`: fully supported (default)
- `whisper_cpp`: exposed in API/UI but not yet implemented

If `whisper_cpp` is selected, the job will fail with a "not implemented" error until `app/transcribe/whisper_cpp_engine.py` is implemented.

---

## Requirements

| Tool | Version |
|------|---------|
| macOS (Apple Silicon) | Sonoma 14+ recommended |
| Python | 3.11+ |
| Node.js | 18+ |
| FFmpeg | latest via Homebrew |

---

## Quick Start

### 1. Install FFmpeg

```bash
brew install ffmpeg
```

### 2. Open the project

```bash
cd /path/to/subtitler
```

### 3. Create and activate Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install backend dependencies

```bash
pip install -r requirements.txt
```

### 5. Run backend

```bash
uvicorn app.main:app --reload --port 8001
```

### 6. Run frontend (dev mode)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 7. Optional production frontend build

```bash
cd frontend
npm run build
cd ..
uvicorn app.main:app --port 8001
```

Open `http://localhost:8001`.

---

## Usage

1. Drop or browse for a file.
2. Choose language, model, and engine.
3. Click **Start Transcription**.
4. Watch real-time logs and progress.
5. Download the generated `.srt` file when complete.

### Accepted file extensions (backend enforced)

- `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`
- `.m4v`, `.mpg`, `.mpeg`, `.wmv`, `.flv`, `.3gp`

Note: The frontend file picker currently shows some audio formats, but backend validation only accepts the extensions listed above.

### Job lifecycle

```text
uploaded -> extracting_audio -> transcribing -> generating_srt -> completed
                                                             -> failed
```

---

## Configuration

Settings are loaded from environment variables with prefix `SUBTITLER_`.
A local `.env` file is also supported.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBTITLER_MAX_FILE_SIZE_MB` | `4096` | Max upload size in MB |
| `SUBTITLER_DEFAULT_MODEL` | `large-v3-turbo` | Default model |
| `SUBTITLER_DEFAULT_LANGUAGE` | `auto` | Default language |
| `SUBTITLER_DEFAULT_ENGINE` | `mlx` | Default engine |

Example:

```bash
SUBTITLER_DEFAULT_MODEL=medium uvicorn app.main:app --reload --port 8001
```

---

## Models

Current model keys exposed by `/api/config`:

- `large-v3-turbo`
- `large-v3`
- `medium`
- `small`
- `base`
- `tiny`

These map to MLX-compatible HuggingFace repositories in `app/config.py`.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/upload` | Upload file and start transcription job |
| `GET` | `/api/jobs/{job_id}` | Get job metadata/status |
| `GET` | `/api/jobs/{job_id}/logs` | SSE stream of logs and status |
| `GET` | `/api/jobs/{job_id}/download-srt` | Download completed `.srt` |
| `GET` | `/api/config` | Get models, languages, engines, defaults |

---

## Project Structure

```text
subtitler/
├── app/
│   ├── main.py
│   ├── config.py
│   ├── jobs.py
│   ├── audio.py
│   ├── subtitles/
│   │   └── srt.py
│   ├── transcribe/
│   │   ├── base.py
│   │   ├── mlx_engine.py
│   │   └── whisper_cpp_engine.py
│   └── utils/
│       └── files.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── api.js
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
├── storage/
│   ├── uploads/
│   ├── audio/
│   └── outputs/
├── tests/
│   └── test_srt.py
├── requirements.txt
└── .gitignore
```

---

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## Security Notes

- Filenames are sanitized to reduce path traversal risk.
- File type is validated by extension and magic-byte detection.
- Upload size limits are enforced while streaming.
- Temporary upload/audio artifacts are cleaned up on success and failure.
- Processing is local-only.

---

## Roadmap

### Implement `whisper_cpp` engine

1. Install `pywhispercpp`.
2. Download a `.bin` model from whisper.cpp releases.
3. Implement `WhisperCppEngine.transcribe()` in `app/transcribe/whisper_cpp_engine.py`.
4. Add dedicated model mapping/validation for whisper.cpp models if needed.
