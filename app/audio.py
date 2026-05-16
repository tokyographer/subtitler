import asyncio
import shutil
import subprocess
from pathlib import Path


class AudioExtractionError(Exception):
    pass


def _ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None


async def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract and convert audio to 16 kHz mono WAV using FFmpeg."""
    if not _ffmpeg_present():
        raise AudioExtractionError(
            "ffmpeg not found. Install with: brew install ffmpeg"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",                   # overwrite without asking
        "-i", str(video_path),
        "-vn",                  # drop video stream
        "-acodec", "pcm_s16le", # 16-bit signed PCM
        "-ar", "16000",         # 16 kHz sample rate
        "-ac", "1",             # mono
        "-f", "wav",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise AudioExtractionError(
            f"FFmpeg failed (exit {proc.returncode}): {stderr.decode(errors='replace')[-500:]}"
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AudioExtractionError("FFmpeg produced no output file.")

    return output_path


async def get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds, or 0 if it cannot be determined."""
    if not _ffmpeg_present():
        return 0.0

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0
