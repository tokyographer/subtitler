# Subtitler

Local macOS app that turns video and audio files into YouTube-compatible `.srt` subtitle files and readable transcripts.

Runs fully on-device on Apple Silicon using `mlx-whisper`. No cloud APIs required for transcription. No Docker.

---

## Features

- Drag-and-drop upload — video and audio files accepted
- Dual transcription engine: **mlx-whisper** (default, Apple Silicon) and **whisper.cpp** (Metal/Core ML)
- Real-time progress and logs via Server-Sent Events (SSE)
- Multilingual-aware — preserves all languages by default; focus language is a Whisper decoding hint, not a content filter
- Hallucination/repetition-loop detection with two-factor guard — always preserves the raw SRT, generates a clean `safe_transcript.srt` separately
- On-demand **transcript reconstruction** — merges subtitle fragments into a clean, readable `.md` document via **Claude API** or a local **Ollama** model (free, no API key needed)
- YouTube-compatible SRT output (42-char line wrap, millisecond timestamps)
- Separate optional interpreter/translation-track filter for simultaneous-interpretation audio
- File validation by extension and magic bytes (MIME sniffing)
- Automatic cleanup of upload and audio artifacts after transcription

---

## Engine Status

| Engine | Status | Notes |
|--------|--------|-------|
| `mlx` | ✅ Default | Apple Silicon Neural Engine + GPU via MLX framework |
| `whisper_cpp` | ✅ Supported | Metal GPU; optional Core ML for max speed |

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

### 2. Install backend dependencies

```bash
cd /path/to/subtitler
uv sync          # preferred
# or: pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — add SUBTITLER_ANTHROPIC_API_KEY if you want transcript generation
```

### 4. Run the backend

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8001
```

### 5. Run the frontend (dev mode)

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

### Production build (single server on port 8001)

```bash
cd frontend && npm run build
cd ..
uvicorn app.main:app --port 8001   # http://localhost:8001
```

---

## Usage

1. Drop or browse for a video or audio file.
2. Choose **Focus language**, **Model**, and **Engine**.
3. Optionally expand **Advanced options** to enable transcript generation or the interpreter filter.
4. Click **Start Transcription**.
5. Watch real-time logs and progress bar.
6. Download the `.srt` file when complete.
7. Optionally click **Generate Transcript** for a clean readable document.

### Accepted formats

**Video:** `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.mpg`, `.mpeg`, `.wmv`, `.flv`, `.3gp`

**Audio:** `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.opus`, `.wma`, `.aiff`, `.aif`

### Job lifecycle

```
uploaded → extracting_audio → transcribing → generating_srt → completed
                                                             → failed
```

### Output files

| File | When created | Contents |
|------|-------------|---------|
| `raw_transcript.srt` | Always | Full Whisper output including any detected loop |
| `safe_transcript.srt` | Loop detected | Clean segments before the loop started |
| `postprocess_report.json` | Loop detected | Loop details: start time, repeated text, segment counts |
| `transcript.md` | On request | Reconstructed readable transcript (Claude or Ollama) |

---

## Advanced Options

| Option | Default | Description |
|--------|---------|-------------|
| **Generate transcript after SRT** | Off | Automatically reconstructs a readable transcript when the SRT completes. Choose provider (Claude or Ollama) and, when Ollama is selected, pick the model from a live dropdown of installed models. |
| **Filter interpreter / translation track** | Off | Removes live interpreter segments when the audio has a main speaker followed by a translator repeating the content in another language. Multilingual content is always preserved by default — this filter is only for simultaneous-interpretation recordings. |

---

## Transcript Generation

When enabled, the transcript is reconstructed from the completed SRT:

- Strips all timestamps and sequence numbers
- Merges subtitle fragments into complete sentences and paragraphs
- Structures content into sections with headings
- Preserves all languages — never translates
- Marks unclear or unintelligible passages as `[?]` instead of inventing content
- Notes transcription artifacts, language switches, and suspected missing audio

Two providers are available — select per-job in the UI:

### Claude (default)

Uses the Claude API (`claude-sonnet-4-6` by default). Requires `SUBTITLER_ANTHROPIC_API_KEY` in `.env`.

### Ollama (local, free)

Uses a locally running [Ollama](https://ollama.com) server. No API key or internet connection needed. The UI shows a live dropdown of all models you have installed; select any model per job without restarting the server.

**Setup:**

```bash
# Install Ollama (https://ollama.com)
brew install ollama

# Pull a model — llama3.1:8b is a good default; use a 32b model for best quality
ollama pull llama3.1:8b

# Start the Ollama server (runs on http://localhost:11434 by default)
ollama serve
```

Enable as default in `.env`:

```
SUBTITLER_TRANSCRIPT_PROVIDER=ollama
SUBTITLER_OLLAMA_MODEL=llama3.1:8b
```

> **Note on large models:** 32b+ models on long SRTs can take 20–30 minutes. The Ollama client uses streaming so it won't time out as long as tokens keep arriving.

---

## Hallucination Detection

Whisper can enter repetition loops on long or difficult audio. The detector uses a two-factor guard:

1. **Run length ≥ 20** consecutive identical segments
2. **Loop represents ≥ 10%** of all segments

Both conditions must be met. This prevents short conversational repetition ("Right, right, right…" × 11 in a 1,000-segment file) from being misclassified as a hallucination.

When a loop is detected:
- `raw_transcript.srt` always contains the full output
- `safe_transcript.srt` contains only the clean segments before the loop
- The UI warning shows focus language, loop start time, repeated text, and segment count
- If a specific focus language was already set, the advice does **not** say "try setting a language"

---

## Configuration

All settings use the `SUBTITLER_` prefix and can be set in `.env` or as environment variables.

| Variable | Default | Description |
|----------|---------|-------------|
| `SUBTITLER_TRANSCRIPT_PROVIDER` | `claude` | `claude` or `ollama` — default transcript provider |
| `SUBTITLER_ANTHROPIC_API_KEY` | — | Required when provider is `claude` |
| `SUBTITLER_TRANSCRIPT_MODEL` | `claude-sonnet-4-6` | Claude model for transcript reconstruction |
| `SUBTITLER_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `SUBTITLER_OLLAMA_MODEL` | `llama3.1:8b` | Default Ollama model (overridable per-job in the UI) |
| `SUBTITLER_OLLAMA_NUM_CTX` | `65536` | Ollama context window (tokens); 64k fits safely in 32 GB RAM |
| `SUBTITLER_DEFAULT_MODEL` | `large-v3-turbo` | Default Whisper model |
| `SUBTITLER_DEFAULT_LANGUAGE` | `auto` | Default focus language |
| `SUBTITLER_DEFAULT_ENGINE` | `mlx` | `mlx` or `whisper_cpp` |
| `SUBTITLER_MAX_FILE_SIZE_MB` | `4096` | Upload size cap |
| `SUBTITLER_HF_CACHE_DIR` | `~/.cache/huggingface` | Custom model cache path |
| `SUBTITLER_FFMPEG_HWACCEL` | `true` | VideoToolbox on Apple Silicon |
| `SUBTITLER_WHISPER_CPP_BINARY` | auto | Explicit path to `whisper-cli` |
| `SUBTITLER_WHISPER_CPP_MODEL_DIR` | — | Directory containing GGML `.bin` files |
| `SUBTITLER_WHISPER_CPP_THREADS` | `0` (auto) | CPU thread count for whisper.cpp |
| `SUBTITLER_WHISPER_CPP_USE_COREML` | `false` | Core ML inference (requires matching build) |

---

## Models

Models are downloaded automatically from HuggingFace on first use and cached locally. Subsequent runs load from disk.

| Model | Size | Best for |
|-------|------|---------|
| `large-v3-turbo` | ~1.5 GB | Default — best accuracy/speed balance |
| `large-v3` | ~3 GB | Maximum accuracy, slower |
| `medium` | ~750 MB | Good accuracy, ~2× faster |
| `small` | ~250 MB | Fast drafts |
| `base` | ~100 MB | Quick checks |
| `tiny` | ~75 MB | Near-instant, rough output |

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/jobs/upload` | Upload file and start transcription |
| `GET` | `/api/jobs/{job_id}` | Job metadata and status |
| `GET` | `/api/jobs/{job_id}/logs` | SSE stream — logs, status, progress |
| `GET` | `/api/jobs/{job_id}/download-srt` | Download best SRT (safe if loop detected, raw otherwise) |
| `GET` | `/api/jobs/{job_id}/download-raw-srt` | Download raw SRT (always, includes any loop) |
| `POST` | `/api/jobs/{job_id}/transcript` | Start transcript generation (async); body: `{ "provider": "claude"\|"ollama", "ollama_model": "..." }` |
| `GET` | `/api/jobs/{job_id}/download-transcript` | Download reconstructed transcript `.md` |
| `GET` | `/api/config` | Models, languages, engines, defaults |

---

## Performance (Apple Silicon M-series)

### Pipeline

1. **Upload** — streamed in 1 MB chunks, never held fully in RAM
2. **Audio extraction** — FFmpeg piped directly to a float32 numpy array; no WAV written to disk; VideoToolbox hardware acceleration on Apple Silicon
3. **Transcription** — runs in a thread pool via `asyncio.to_thread`; mlx-whisper uses the Neural Engine and GPU cores
4. **SRT generation** — CPU-only, completes in milliseconds
5. **Cleanup** — upload file deleted as soon as audio is in RAM

### Expected speeds (large-v3-turbo on M-series)

| Content length | Transcription time |
|---------------|-------------------|
| 5 min | ~20–40 s |
| 30 min | ~2–4 min |
| 60 min | ~4–8 min |
| 90 min | ~6–12 min |

`medium` and `small` run ~2× and ~4× faster with lower accuracy.

---

## whisper.cpp Engine

An alternative backend using Metal GPU (or Core ML Neural Engine). Useful for CPU-only machines or when you want a second engine option.

### Install via Homebrew

```bash
brew install whisper-cpp
```

Verify: `whisper-cli --help`

### Build from source with Metal

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_METAL=ON
cmake --build build -j$(sysctl -n hw.logicalcpu) --config Release
```

### Build with Core ML (fastest)

```bash
pip install coremltools
cmake -B build -DWHISPER_COREML=ON
cmake --build build -j$(sysctl -n hw.logicalcpu)

# Convert model
cd models
python convert-whisper-to-coreml.py --model large-v3-turbo
```

Enable in `.env`:
```
SUBTITLER_WHISPER_CPP_USE_COREML=true
```

### Download GGML models

```bash
mkdir -p ~/whisper-models
curl -L -o ~/whisper-models/ggml-large-v3-turbo.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
```

### Configure

```bash
SUBTITLER_WHISPER_CPP_MODEL_DIR=/Users/you/whisper-models
SUBTITLER_WHISPER_CPP_BINARY=/opt/homebrew/bin/whisper-cli   # optional
```

The UI shows **(not installed)** if the binary or model directory is missing.

---

## Project Structure

```
subtitler/
├── app/
│   ├── main.py                  # FastAPI app, routes, SSE, background pipeline
│   ├── config.py                # Pydantic Settings (SUBTITLER_ prefix)
│   ├── jobs.py                  # Job dataclass + thread-safe JobStore
│   ├── audio.py                 # FFmpeg pipe → float32 numpy array
│   ├── transcript.py            # Transcript reconstruction — Claude API or Ollama (streaming)
│   ├── subtitles/
│   │   └── srt.py               # Timestamp formatting, line wrap, SRT output
│   ├── transcribe/
│   │   ├── base.py              # Abstract TranscriptionEngine, TranscriptionOptions, Segment
│   │   ├── mlx_engine.py        # mlx-whisper engine (Apple Silicon default)
│   │   ├── whisper_cpp_engine.py # whisper.cpp CLI subprocess engine
│   │   └── postprocess.py       # Loop detection (detect_loop), translation filter
│   └── utils/
│       └── files.py             # Upload validation, streaming save, cleanup
├── frontend/
│   └── src/
│       ├── App.jsx              # Single-component UI
│       ├── App.css
│       └── api.js               # Fetch wrappers for all API endpoints
├── tests/
│   ├── test_srt.py
│   └── test_postprocess.py
├── .env.example
└── requirements.txt
```

---

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v

# Single file
pytest tests/test_postprocess.py -v
```

69 tests covering SRT generation, timestamp formatting, loop detection, multilingual preservation, and translation filter isolation.

---

## Security

- File type validated by extension **and** magic bytes — extension alone is not trusted
- Upload size enforced while streaming — never fully buffered before validation
- CORS restricted to localhost origins — `allow_origins=["*"]` is never used
- Uploaded files and SRT output stored in `storage/` (gitignored)
- Anthropic API key loaded from environment only — never logged or exposed in API responses
- No PII logged — only job IDs and file hashes
