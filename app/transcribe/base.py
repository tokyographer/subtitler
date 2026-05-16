from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class Segment:
    __slots__ = ("start", "end", "text")

    def __init__(self, start: float, end: float, text: str):
        self.start = start
        self.end = end
        self.text = text

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text}


class TranscriptionEngine(ABC):
    """
    Abstract base for transcription backends.

    Subclasses must implement :py:meth:`transcribe`.  The engine is responsible
    for model loading on first use; callers should not assume the constructor
    performs any heavy initialisation.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'mlx' or 'whisper_cpp'."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        model: str,
        language: str | None,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        """
        Transcribe *audio_path* and return a list of :class:`Segment` objects.

        Parameters
        ----------
        audio_path:
            Path to a 16 kHz mono WAV file.
        model:
            Short model name as in ``settings.mlx_model_repos`` (e.g.
            ``"large-v3-turbo"``).
        language:
            ISO 639-1 language code, or ``None`` / ``"auto"`` for auto-detection.
        progress_cb:
            Optional callable that receives an integer 0-100 as the engine
            makes progress.  Implementations may call it at coarse granularity.
        """
