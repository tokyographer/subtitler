from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from app.config import settings
from app.transcribe.base import Segment, TranscriptionEngine


class MLXWhisperEngine(TranscriptionEngine):
    """
    Transcription engine backed by mlx-whisper.
    Optimised for Apple Silicon via the MLX framework.
    """

    @property
    def name(self) -> str:
        return "mlx"

    def _resolve_repo(self, model: str) -> str:
        repo = settings.mlx_model_repos.get(model)
        if repo is None:
            raise ValueError(
                f"Unknown model '{model}'. "
                f"Available: {', '.join(settings.mlx_model_repos)}"
            )
        return repo

    def transcribe(
        self,
        audio_path: Path,
        model: str,
        language: str | None,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        try:
            import mlx_whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is not installed. Run: pip install mlx-whisper"
            ) from exc

        repo = self._resolve_repo(model)
        lang = None if language in (None, "auto") else language

        # mlx_whisper.transcribe is synchronous; the caller runs us in a thread.
        # We simulate progress with a background ticker while transcription runs.
        _stop_event = threading.Event()
        if progress_cb:
            self._start_progress_ticker(progress_cb, _stop_event)

        try:
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=repo,
                language=lang,
                verbose=False,
            )
        finally:
            _stop_event.set()

        if progress_cb:
            progress_cb(100)

        raw_segments = result.get("segments", [])
        return [
            Segment(
                start=float(s["start"]),
                end=float(s["end"]),
                text=s["text"],
            )
            for s in raw_segments
            if s.get("text", "").strip()
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _start_progress_ticker(
        progress_cb: Callable[[int], None],
        stop_event: threading.Event,
    ) -> None:
        """
        Tick progress from 0→98 using a logarithmic curve so it looks natural.
        The caller sets stop_event when transcription finishes.
        """
        import math
        import time

        def _run():
            elapsed = 0.0
            # Aim to reach ~90 % in ~120 s (reasonable for large-v3-turbo on M-series)
            T = 120.0
            while not stop_event.is_set():
                pct = int(98 * (1 - math.exp(-elapsed / T)))
                progress_cb(min(pct, 98))
                time.sleep(1.0)
                elapsed += 1.0

        t = threading.Thread(target=_run, daemon=True)
        t.start()
