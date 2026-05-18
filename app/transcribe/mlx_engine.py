from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Union

from app.config import settings
from app.transcribe.base import Segment, TranscriptionEngine, TranscriptionOptions

if TYPE_CHECKING:
    import numpy as np


class MLXWhisperEngine(TranscriptionEngine):
    """
    Transcription engine backed by mlx-whisper.
    Runs natively on Apple Silicon via the MLX framework (Neural Engine + GPU).
    """

    @property
    def name(self) -> str:
        return "mlx"

    def is_available(self) -> tuple[bool, str]:
        try:
            import mlx_whisper  # noqa: F401
            return True, ""
        except ImportError:
            return False, "mlx-whisper not installed. Run: pip install mlx-whisper"

    def _resolve_repo(self, model: str) -> str:
        repo = settings.mlx_model_repos.get(model)
        if repo is None:
            raise ValueError(
                f"Unknown model '{model}'.\n"
                f"Available models: {', '.join(settings.mlx_model_repos)}\n"
                "Check your model name or add a new entry in config.py."
            )
        return repo

    def _apply_hf_cache(self) -> None:
        """Point HuggingFace downloads at the configured cache directory."""
        if settings.hf_cache_dir:
            cache = str(settings.hf_cache_dir)
            os.environ.setdefault("HF_HOME", cache)
            os.environ.setdefault("HUGGINGFACE_HUB_CACHE", cache)

    def transcribe(
        self,
        audio: Union[Path, "np.ndarray"],
        model: str,
        language: str | None,
        options: TranscriptionOptions,
        progress_cb: Callable[[int], None] | None = None,
    ) -> list[Segment]:
        try:
            import mlx_whisper  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "mlx-whisper is not installed.\n"
                "Run:  pip install mlx-whisper\n"
                "Then restart the server."
            ) from exc

        self._apply_hf_cache()

        repo = self._resolve_repo(model)
        lang = None if language in (None, "auto") else language

        # mlx_whisper.transcribe() is synchronous — the caller runs us in a
        # thread via asyncio.to_thread().  Simulate progress with a background
        # ticker while waiting for it to complete.
        stop_event = threading.Event()
        if progress_cb:
            self._start_progress_ticker(progress_cb, stop_event)

        try:
            # Accept either a file path or a pre-decoded numpy array.
            audio_input = audio if not isinstance(audio, Path) else str(audio)

            # Scalar 0.0 disables Whisper's temperature fallback recovery — bad
            # segments would never be retried and hallucination loops cascade.
            # Tuple form enables retry at 0.2, 0.4 … when compression ratio or
            # logprob thresholds are exceeded.
            temperature = (
                (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
                if options.temperature == 0.0
                else options.temperature
            )

            result = mlx_whisper.transcribe(
                audio_input,
                path_or_hf_repo=repo,
                language=lang,
                task=options.task,
                temperature=temperature,
                condition_on_previous_text=options.condition_on_previous_text,
                no_speech_threshold=options.no_speech_threshold,
                compression_ratio_threshold=options.compression_ratio_threshold,
                logprob_threshold=options.logprob_threshold,
                hallucination_silence_threshold=options.hallucination_silence_threshold,
                verbose=False,
            )
        except Exception as exc:
            err = str(exc)
            if "not found" in err.lower() or "no such file" in err.lower():
                raise RuntimeError(
                    f"Model '{model}' could not be loaded from '{repo}'.\n"
                    "The model cache may be incomplete. Delete it and retry:\n"
                    f"  rm -rf ~/.cache/huggingface/hub/{repo.replace('/', '--')}"
                ) from exc
            raise
        finally:
            stop_event.set()

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

    @staticmethod
    def _start_progress_ticker(
        progress_cb: Callable[[int], None],
        stop_event: threading.Event,
    ) -> None:
        """
        Logarithmic progress ticker: 0 → 98 % over ~120 s.
        Calibrated for large-v3-turbo on M-series at ~4× real-time.
        """
        import math
        import time

        def _run() -> None:
            elapsed = 0.0
            T = 120.0  # time constant (seconds)
            while not stop_event.is_set():
                pct = int(98 * (1 - math.exp(-elapsed / T)))
                progress_cb(min(pct, 98))
                time.sleep(0.5)
                elapsed += 0.5

        threading.Thread(target=_run, daemon=True).start()
