from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUBTITLER_", env_file=".env", extra="ignore")

    storage_uploads: Path = BASE_DIR / "storage" / "uploads"
    storage_audio: Path = BASE_DIR / "storage" / "audio"
    storage_outputs: Path = BASE_DIR / "storage" / "outputs"

    max_file_size_mb: int = 4096  # 4 GB

    allowed_extensions: frozenset = frozenset({
        ".mp4", ".mov", ".avi", ".mkv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".3gp",
    })

    allowed_mime_prefixes: frozenset = frozenset({
        "video/",
        "application/octet-stream",  # some browsers send this for .mkv
    })

    default_model: str = "large-v3-turbo"
    default_language: str = "auto"
    default_engine: str = "mlx"

    # MLX model HuggingFace repos
    mlx_model_repos: dict = {
        "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "medium": "mlx-community/whisper-medium-mlx",
        "small": "mlx-community/whisper-small-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "tiny": "mlx-community/whisper-tiny-mlx",
    }

    # Supported languages (ISO 639-1 codes); "auto" means detect
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

for _d in (settings.storage_uploads, settings.storage_audio, settings.storage_outputs):
    _d.mkdir(parents=True, exist_ok=True)
