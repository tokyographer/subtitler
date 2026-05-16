"""
Audio extraction via FFmpeg pipe → numpy array.

Audio is never written to disk; it is piped directly from FFmpeg into a
float32 numpy array at 16 kHz mono and passed straight to the transcription
engine.  This saves one full disk write per job — significant for large files
on any storage, and especially on RAM-constrained systems.

Hardware acceleration:
  - ``-hwaccel auto`` lets FFmpeg pick the best available decoder.
    On Apple Silicon this resolves to VideoToolbox.
  - ``-threads 0`` uses all available CPU threads for demuxing/decoding.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from app.config import settings


class AudioExtractionError(Exception):
    pass


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise AudioExtractionError(
            "FFmpeg is not installed.\n"
            "Install it with Homebrew:  brew install ffmpeg\n"
            "Then restart the server."
        )


async def extract_audio(video_path: Path) -> "np.ndarray":
    """
    Extract 16 kHz mono audio from *video_path* and return a float32 numpy
    array normalised to [-1, 1].  No intermediate file is written to disk.

    Raises
    ------
    AudioExtractionError
        On any FFmpeg failure, with a user-friendly message.
    """
    import numpy as np

    _require_ffmpeg()

    cmd = [
        "ffmpeg",
        "-nostdin",              # never read from stdin
        "-hide_banner",
        "-loglevel", "error",    # suppress progress spam; keep errors
        "-threads", "0",         # use all CPU threads for demux / decode
    ]

    if settings.ffmpeg_hwaccel:
        # VideoToolbox on Apple Silicon; auto-selects best available elsewhere
        cmd += ["-hwaccel", "auto"]

    cmd += [
        "-i", str(video_path),
        "-vn", "-sn", "-dn",    # drop video, subtitle, data streams
        "-acodec", "pcm_s16le",  # 16-bit signed PCM
        "-ar", "16000",          # 16 kHz
        "-ac", "1",              # mono
        "-f", "s16le",           # raw PCM → stdout (no WAV header overhead)
        "-",
    ]

    # 512 MB pipe buffer covers ~9 hours of 16 kHz mono audio — enough for any
    # practical recording on a 32 GB machine.
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=512 * 1024 * 1024,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        _raise_ffmpeg_error(stderr.decode(errors="replace"), video_path)

    if not stdout:
        raise AudioExtractionError(
            f"FFmpeg produced no audio from '{video_path.name}'.\n"
            "The file may have no audio track."
        )

    audio = np.frombuffer(stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


async def get_duration(path: Path) -> float:
    """Return media duration in seconds, or 0.0 if undetermined."""
    if not shutil.which("ffprobe"):
        return 0.0
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
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


def _raise_ffmpeg_error(stderr: str, path: Path) -> None:
    tail = stderr[-1000:]
    name = path.name
    if "No such file or directory" in tail:
        raise AudioExtractionError(f"File not found: {name}")
    if "Invalid data found" in tail or "moov atom not found" in tail:
        raise AudioExtractionError(
            f"Cannot read '{name}' — the file may be corrupt or truncated."
        )
    if "no audio" in tail.lower() or "does not contain" in tail.lower():
        raise AudioExtractionError(f"No audio track found in '{name}'.")
    if "codec not currently supported" in tail.lower():
        raise AudioExtractionError(
            f"Unsupported codec in '{name}'. "
            "Try re-encoding with HandBrake or ffmpeg first."
        )
    raise AudioExtractionError(
        f"FFmpeg failed while processing '{name}':\n{tail}"
    )
