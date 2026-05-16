from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Union

from app.transcribe.base import Segment, TranscriptionEngine, TranscriptionOptions

if TYPE_CHECKING:
    import numpy as np


class WhisperCppEngine(TranscriptionEngine):
    """
    Transcription engine backed by whisper.cpp.

    TODO: implement when pywhispercpp bindings are added.

    Steps to integrate:
      1. pip install pywhispercpp
      2. Download a .bin model from github.com/ggerganov/whisper.cpp/releases
      3. Set SUBTITLER_WHISPER_CPP_MODEL_DIR in .env
      4. Implement transcribe() below using pywhispercpp.Model

    Example:
        from pywhispercpp.model import Model
        m = Model(model_path)
        segs = m.transcribe(str(audio_path), language=language or "auto")
        return [Segment(s.t0 / 100, s.t1 / 100, s.text) for s in segs]
    """

    @property
    def name(self) -> str:
        return "whisper_cpp"

    def transcribe(
        self,
        audio: Union[Path, "np.ndarray"],
        model: str,
        language: str | None,
        options: TranscriptionOptions,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        raise NotImplementedError(
            "whisper.cpp engine is not yet implemented.\n"
            "Switch to engine='mlx' (the default) or implement "
            "WhisperCppEngine.transcribe() in app/transcribe/whisper_cpp_engine.py."
        )
