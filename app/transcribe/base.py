from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Union

if TYPE_CHECKING:
    import numpy as np


@dataclass
class TranscriptionOptions:
    """
    All tunable parameters passed from the API through to the engine.
    Defaults mirror the backend config; callers can override per-job.
    """
    task: str = "transcribe"               # "transcribe" | "translate"
    temperature: float = 0.0               # 0 = greedy / fastest
    condition_on_previous_text: bool = True
    no_speech_threshold: float = 0.6
    max_line_chars: int = 42               # SRT line wrap width
    max_segment_duration: float = 0.0      # cap display duration (0 = unlimited)
    merge_gap_ms: int = 0                  # merge segments closer than N ms (0 = off)


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

    Subclasses accept either a file path or a pre-decoded numpy float32 array
    at 16 kHz mono.  The engine is responsible for model loading on first use.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier, e.g. 'mlx' or 'whisper_cpp'."""

    @abstractmethod
    def transcribe(
        self,
        audio: Union[Path, "np.ndarray"],
        model: str,
        language: str | None,
        options: TranscriptionOptions,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        """
        Transcribe *audio* and return a list of :class:`Segment` objects.

        Parameters
        ----------
        audio:
            Either a Path to a 16 kHz mono WAV/raw audio file, or a float32
            numpy array at 16 kHz mono already in RAM.
        model:
            Short model name (key in ``settings.mlx_model_repos``).
        language:
            ISO 639-1 code, or ``None`` for auto-detection.
        options:
            Transcription parameters.
        progress_cb:
            Optional callable receiving an integer 0–100 as the engine progresses.
        """
