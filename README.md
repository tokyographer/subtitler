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

## Performance Tuning (Apple Silicon M-series)

### How the pipeline works

1. **Upload** streams in 1 MB chunks — the server never holds the whole file in RAM during upload.
2. **Audio extraction** pipes FFmpeg output directly to a numpy float32 array via `asyncio`. No WAV file is written to disk. FFmpeg uses `-hwaccel auto` which resolves to VideoToolbox on Apple Silicon and `-threads 0` for optimal CPU threading.
3. **Transcription** runs in a thread pool via `asyncio.to_thread` so the API stays responsive. mlx-whisper executes on the Neural Engine / GPU cores via Apple MLX.
4. **SRT generation** is CPU-only and completes in milliseconds.
5. **Upload file** is deleted as soon as audio is decoded to RAM, freeing disk space immediately.

### Expected speeds on M5 32 GB (large-v3-turbo)

| Content length | Approx. transcription time |
|---------------|---------------------------|
| 5 min         | ~20–40 s                  |
| 30 min        | ~2–4 min                  |
| 60 min        | ~4–8 min                  |
| 120 min       | ~8–16 min                 |

`medium` and `small` models run ~2× and ~4× faster respectively with lower accuracy.

### Model selection guide

| Model | Size | Best for |
|-------|------|---------|
| `large-v3-turbo` | ~1.5 GB | Default — best accuracy/speed balance |
| `large-v3` | ~3 GB | Maximum accuracy, slow |
| `medium` | ~750 MB | Good accuracy, ~2× faster than large |
| `small` | ~250 MB | Fast drafts, lower accuracy |
| `tiny` | ~75 MB | Near-instant, rough output |

### Environment variables

```bash
# Custom HuggingFace model cache (e.g. fast NVMe or external SSD)
SUBTITLER_HF_CACHE_DIR=/Volumes/FastDrive/.cache/huggingface

# Disable VideoToolbox (e.g. when testing on non-Apple hardware)
SUBTITLER_FFMPEG_HWACCEL=false

# Raise the upload size limit (default 4096 MB)
SUBTITLER_MAX_FILE_SIZE_MB=8192
```

Put these in a `.env` file in the project root, or export them before starting the server.

### RAM disk for uploads (optional, advanced)

On macOS you can create a RAM disk for the upload staging area, which makes the upload-to-transcription handoff slightly faster:

```bash
# Create a 2 GB RAM disk
diskutil erasevolume HFS+ 'SubtitlerRAM' $(hdiutil attach -nomount ram://4194304)

# Point uploads at it
echo 'SUBTITLER_STORAGE_UPLOADS=/Volumes/SubtitlerRAM/uploads' >> .env
```

The RAM disk is lost on reboot; uploads are deleted after transcription anyway.

### Advanced options (UI)

| Option | What it does |
|--------|-------------|
| **Translate to English** | Uses Whisper's built-in translation. Best for common languages (Spanish, French, German, Japanese, etc.). |
| **Max line length** | Characters per SRT line before wrapping. YouTube recommends ≤ 42. Increase to 56–72 for widescreen players. |
| **Max display duration** | Caps how long each subtitle block stays on screen. Useful for fast speech where Whisper creates very long segments. 0 = no cap. |
| **Merge gap** | Joins consecutive segments separated by less than N milliseconds. Reduces subtitle flicker for presentations or podcasts. 0 = off. |

---

## Roadmap

### Implement `whisper_cpp` engine

1. Install `pywhispercpp`.
2. Download a `.bin` model from whisper.cpp releases.
3. Implement `WhisperCppEngine.transcribe()` in `app/transcribe/whisper_cpp_engine.py`.
4. Add dedicated model mapping/validation for whisper.cpp models if needed.
