from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBTITLER_", env_file=".env", extra="ignore")

    # ── Storage ───────────────────────────────────────────────────────────
    storage_uploads: Path = BASE_DIR / "storage" / "uploads"
    storage_outputs: Path = BASE_DIR / "storage" / "outputs"

    max_file_size_mb: int = 4096  # 4 GB

    # ── Model cache ───────────────────────────────────────────────────────
    # Set to a fast NVMe path or a RAM disk for best performance.
    # None → HuggingFace default (~/.cache/huggingface)
    hf_cache_dir: Optional[Path] = None

    # ── File validation ───────────────────────────────────────────────────
    allowed_extensions: frozenset = frozenset({
        # video
        ".mp4", ".mov", ".avi", ".mkv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp",
        # audio
        ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac",
        ".opus", ".wma", ".aiff", ".aif",
    })

    allowed_mime_prefixes: frozenset = frozenset({
        "video/",
        "audio/",
        "application/octet-stream",  # some browsers use this for .mkv
    })

    # ── FFmpeg ────────────────────────────────────────────────────────────
    # VideoToolbox hardware acceleration; set False to disable on non-Apple hardware.
    ffmpeg_hwaccel: bool = True

    # ── Transcription defaults ────────────────────────────────────────────
    default_model: str = "large-v3-turbo"
    default_language: str = "auto"
    default_engine: str = "mlx"
    default_task: str = "transcribe"          # "transcribe" | "translate"
    default_temperature: float = 0.0          # 0 = greedy (fastest, deterministic)
    default_condition_on_previous: bool = False  # True enables hallucination cascades
    default_no_speech_threshold: float = 0.6
    default_max_line_chars: int = 42
    default_max_segment_duration: float = 0.0  # 0 = no cap
    default_merge_gap_ms: int = 0              # 0 = disabled
    default_compression_ratio_threshold: float = 2.4
    default_logprob_threshold: float = -1.0
    repetition_loop_max_run: int = 20          # consecutive identical segments required (real loops are hundreds)
    repetition_loop_min_fraction: float = 0.10  # loop segments must be >= this fraction of total

    # ── whisper.cpp ───────────────────────────────────────────────────────
    # Path to the whisper-cli binary. None = auto-detect from PATH and common locations.
    whisper_cpp_binary: Optional[str] = None
    # Directory containing ggml *.bin model files.
    whisper_cpp_model_dir: Optional[Path] = None
    # CPU threads for whisper.cpp. 0 = auto (half of os.cpu_count()).
    whisper_cpp_threads: int = 0
    # Enable Core ML inference (requires a Core ML-enabled whisper.cpp build
    # and pre-converted *.mlmodelc model files alongside the .bin file).
    whisper_cpp_use_coreml: bool = False

    # ── Transcript generation ─────────────────────────────────────────────
    transcript_provider: str = "claude"           # "claude" | "ollama"
    anthropic_api_key: Optional[str] = None
    transcript_model: str = "claude-sonnet-4-6"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_num_ctx: int = 65536   # context window; llama3.1:8b trains to 131072 but 64k fits safely in 32 GB RAM
    ollama_timeout: int = 1800    # seconds; 32b models on long SRTs can take 20-30 min

    # ── MLX model repos ───────────────────────────────────────────────────
    mlx_model_repos: dict = {
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
        "large-v3":       "mlx-community/whisper-large-v3-mlx",
        "medium":         "mlx-community/whisper-medium-mlx",
        "small":          "mlx-community/whisper-small-mlx",
        "base":           "mlx-community/whisper-base-mlx",
        "tiny":           "mlx-community/whisper-tiny-mlx",
    }

    # ── Languages ─────────────────────────────────────────────────────────
    supported_languages: dict = {
        "auto": "Auto-detect",
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "ja": "Japanese",
        "zh": "Chinese",
        "ko": "Korean",
        "pt": "Portuguese",
        "it": "Italian",
        "ru": "Russian",
        "ar": "Arabic",
    }


settings = Settings()

for _d in (settings.storage_uploads, settings.storage_outputs):
    _d.mkdir(parents=True, exist_ok=True)
