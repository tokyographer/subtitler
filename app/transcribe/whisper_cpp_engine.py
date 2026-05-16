from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.transcribe.base import Segment, TranscriptionEngine


class WhisperCppEngine(TranscriptionEngine):
    """
    Transcription engine backed by whisper.cpp.

    TODO: implement when whisper.cpp Python bindings are added.
    Steps to integrate:
      1. Install pywhispercpp: pip install pywhispercpp
      2. Download a .bin model from ggerganov/whisper.cpp releases.
      3. Set the model path via SUBTITLER_WHISPER_CPP_MODEL_DIR env var.
      4. Implement transcribe() using pywhispercpp.Model.

    Example (pywhispercpp):
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
        audio_path: Path,
        model: str,
        language: str | None,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        raise NotImplementedError(
            "whisper.cpp engine is not yet implemented. "
            "Use engine='mlx' (default) instead."
        )
