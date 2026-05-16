"""
whisper.cpp transcription engine.

Runs the whisper-cli (or legacy ``main``) binary as a subprocess, pipes
audio in via a temporary WAV file, collects JSON output, and converts it to
the app's internal Segment format.

Key design notes
----------------
* Audio arrives as a float32 numpy array from the FFmpeg pipe. We write it
  to a NamedTemporaryFile inside a TemporaryDirectory, pass that path to the
  CLI, and clean everything up on exit — even if transcription fails.
* Progress is parsed from the binary's stderr in a daemon thread so the
  progress bar updates in real time.
* ``--print-progress`` is tried first; if the binary rejects it (older build)
  we fall back silently without the flag.
* The JSON output format has been stable since whisper.cpp v1.2. The ``offsets``
  field (milliseconds) is preferred; timestamp strings are a fallback for any
  future format changes.
* Metal GPU acceleration is used automatically by any Apple Silicon build of
  whisper.cpp — no extra CLI flag is needed.
* Core ML requires a build compiled with ``WHISPER_COREML=1`` **and** a
  pre-converted ``*.mlmodelc`` bundle next to the ``.bin`` model file. Enable
  via ``SUBTITLER_WHISPER_CPP_USE_COREML=true`` in ``.env``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable, Optional, Union

from app.config import settings
from app.transcribe.base import Segment, TranscriptionEngine, TranscriptionOptions

# -----------------------------------------------------------------
# Constants
# -----------------------------------------------------------------

# Binary names to probe (in preference order).
_BINARY_NAMES = ["whisper-cli", "whisper", "main"]

# Common install prefixes beyond PATH.
_EXTRA_BINARY_DIRS = [
    Path.home() / "bin",
    Path.home() / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
]

# Default GGML filename for each short model name.
_MODEL_MAP: dict[str, str] = {
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
    "large-v3":       "ggml-large-v3.bin",
    "medium":         "ggml-medium.bin",
    "small":          "ggml-small.bin",
    "base":           "ggml-base.bin",
    "tiny":           "ggml-tiny.bin",
}

# Matches e.g. "progress = 50%" anywhere in a stderr line.
_PROGRESS_RE = re.compile(r"progress\s*[=:]\s*(\d+)\s*%", re.IGNORECASE)


# -----------------------------------------------------------------
# Engine
# -----------------------------------------------------------------

class WhisperCppEngine(TranscriptionEngine):
    """
    Transcription engine backed by the whisper.cpp CLI.
    Uses Metal GPU acceleration automatically on Apple Silicon.
    """

    @property
    def name(self) -> str:
        return "whisper_cpp"

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> tuple[bool, str]:
        try:
            binary = self._find_binary()
            return True, binary
        except FileNotFoundError as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio: Union[Path, "np.ndarray"],
        model: str,
        language: str | None,
        options: TranscriptionOptions,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> list[Segment]:
        import numpy as np

        binary = self._find_binary()
        model_path = self._find_model(model)

        with tempfile.TemporaryDirectory(prefix="subtitler_wcpp_") as tmpdir:
            tmp = Path(tmpdir)

            # Write audio to a WAV file if we received a numpy array.
            if isinstance(audio, np.ndarray):
                wav_path = tmp / "audio.wav"
                _write_wav(audio, wav_path)
            else:
                wav_path = Path(audio)

            out_prefix = str(tmp / "out")
            threads = settings.whisper_cpp_threads or max(4, (os.cpu_count() or 8) // 2)
            lang_arg = language if (language and language != "auto") else "auto"

            base_cmd = [
                binary,
                "-m",   str(model_path),
                "-f",   str(wav_path),
                "--output-json",
                "--output-file", out_prefix,
                "--language",    lang_arg,
                "--task",        options.task,
                "--threads",     str(threads),
            ]

            if settings.whisper_cpp_use_coreml:
                base_cmd.append("--use-coreml")

            returncode, stderr = self._run(base_cmd + ["--print-progress"], progress_cb)

            # Retry without --print-progress if the binary didn't recognise it.
            if returncode != 0 and _flag_rejected(stderr, "print-progress"):
                returncode, stderr = self._run(base_cmd, progress_cb)

            if returncode != 0:
                _raise_error(returncode, stderr, model, binary)

            json_out = Path(out_prefix + ".json")
            if not json_out.exists():
                raise RuntimeError(
                    "whisper.cpp exited cleanly but produced no JSON file.\n"
                    f"Expected: {json_out}\n"
                    f"Last stderr:\n{stderr[-400:]}"
                )

            segments = _parse_json(json_out)

        if progress_cb:
            progress_cb(100)

        return segments

    # ------------------------------------------------------------------
    # Binary / model discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _find_binary() -> str:
        """Locate the whisper-cli binary. Raises FileNotFoundError if absent."""
        # 1. Explicitly configured path.
        if settings.whisper_cpp_binary:
            p = Path(settings.whisper_cpp_binary)
            if p.is_file():
                return str(p)
            raise FileNotFoundError(
                f"Configured whisper.cpp binary not found: {p}\n"
                "Check SUBTITLER_WHISPER_CPP_BINARY in your .env file."
            )

        # 2. PATH lookup.
        for name in _BINARY_NAMES:
            found = shutil.which(name)
            if found:
                return found

        # 3. Common install dirs not always on PATH (e.g. ~/bin on fresh macOS).
        for d in _EXTRA_BINARY_DIRS:
            for name in _BINARY_NAMES:
                candidate = d / name
                if candidate.is_file():
                    return str(candidate)

        raise FileNotFoundError(
            "whisper.cpp binary not found.\n"
            "Install with:  brew install whisper-cpp\n"
            "Or build from source and set:\n"
            "  SUBTITLER_WHISPER_CPP_BINARY=/path/to/whisper-cli  in .env"
        )

    @staticmethod
    def _find_model(model_key: str) -> Path:
        """Locate the GGML .bin file for *model_key*. Raises FileNotFoundError."""
        model_dir = settings.whisper_cpp_model_dir
        if not model_dir:
            raise FileNotFoundError(
                "No whisper.cpp model directory configured.\n"
                "Set SUBTITLER_WHISPER_CPP_MODEL_DIR=/path/to/models in .env\n"
                "then download models with:\n"
                "  bash models/download-ggml-model.sh large-v3-turbo"
            )
        model_dir = Path(model_dir)
        if not model_dir.exists():
            raise FileNotFoundError(
                f"whisper.cpp model directory not found: {model_dir}\n"
                "Check SUBTITLER_WHISPER_CPP_MODEL_DIR in your .env file."
            )

        # Exact filename from map.
        expected = _MODEL_MAP.get(model_key)
        if expected:
            exact = model_dir / expected
            if exact.exists():
                return exact

        # Glob fallback: accept quantized variants, dated filenames, etc.
        matches = sorted(model_dir.glob(f"*{model_key}*.bin"))
        if matches:
            # Prefer non-quantized (no 'q' suffix token) when available.
            plain = [m for m in matches if not re.search(r"-q\d+", m.name)]
            return plain[0] if plain else matches[0]

        available = [f.name for f in sorted(model_dir.glob("*.bin"))]
        avail_str = "\n  ".join(available) if available else "(none found)"
        raise FileNotFoundError(
            f"Model '{model_key}' not found in {model_dir}.\n"
            f"Expected filename: {expected or f'*{model_key}*.bin'}\n"
            f"Models present:\n  {avail_str}\n"
            "Download from: https://huggingface.co/ggerganov/whisper.cpp"
        )

    # ------------------------------------------------------------------
    # Subprocess execution
    # ------------------------------------------------------------------

    @staticmethod
    def _run(
        cmd: list[str],
        progress_cb: Optional[Callable[[int], None]],
    ) -> tuple[int, str]:
        """
        Execute *cmd*, stream stderr to parse progress, return (returncode, stderr).
        stdout is discarded (whisper.cpp writes output to files, not stdout).
        """
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        stderr_lines: list[str] = []

        def _drain_stderr() -> None:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode(errors="replace").rstrip()
                stderr_lines.append(line)
                if progress_cb:
                    m = _PROGRESS_RE.search(line)
                    if m:
                        progress_cb(int(m.group(1)))
            proc.stderr.close()

        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()
        proc.stdout.read()  # drain to avoid pipe deadlock
        proc.stdout.close()
        t.join()
        proc.wait()

        return proc.returncode, "\n".join(stderr_lines)


# -----------------------------------------------------------------
# Module-level helpers (no shared state, easy to unit-test)
# -----------------------------------------------------------------

def _write_wav(audio: "np.ndarray", path: Path) -> None:
    """Write a float32 [-1, 1] numpy array as 16 kHz mono 16-bit WAV."""
    import numpy as np

    samples = np.clip(audio, -1.0, 1.0)
    pcm = (samples * 32_767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)       # 16-bit = 2 bytes
        wf.setframerate(16_000)
        wf.writeframes(pcm.tobytes())


def _parse_srt_ts(ts: str) -> float:
    """Parse ``"HH:MM:SS,mmm"`` → float seconds."""
    try:
        h, m, s_ms = ts.split(":")
        s, ms = s_ms.replace(",", ".").split(".")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except Exception:
        return 0.0


def _parse_json(json_path: Path) -> list[Segment]:
    """
    Parse whisper.cpp JSON output into Segment objects.

    Supports both the ``offsets`` (ms integers, preferred) and ``timestamps``
    (SRT string fallback) fields present in the stable JSON format.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    segments: list[Segment] = []

    for entry in data.get("transcription", []):
        text = entry.get("text", "").strip()
        if not text:
            continue

        offsets = entry.get("offsets", {})
        if offsets:
            start = offsets.get("from", 0) / 1000.0
            end   = offsets.get("to",   0) / 1000.0
        else:
            ts = entry.get("timestamps", {})
            start = _parse_srt_ts(ts.get("from", "00:00:00,000"))
            end   = _parse_srt_ts(ts.get("to",   "00:00:00,000"))

        segments.append(Segment(start=start, end=end, text=text))

    return segments


def _flag_rejected(stderr: str, flag: str) -> bool:
    """Return True if stderr suggests the binary didn't recognise *flag*."""
    lower = stderr.lower()
    return flag in lower and any(
        word in lower for word in ("unknown", "invalid", "unrecognized", "not recognized")
    )


def _raise_error(returncode: int, stderr: str, model: str, binary: str) -> None:
    tail = stderr[-800:]
    lower = tail.lower()

    if "model" in lower and ("not found" in lower or "failed to load" in lower):
        raise RuntimeError(
            f"whisper.cpp could not load the model '{model}'.\n"
            "Ensure the .bin file is a valid GGML model (not corrupt / truncated).\n"
            f"stderr:\n{tail}"
        )
    if "failed to open" in lower or "no such file" in lower:
        raise RuntimeError(
            "whisper.cpp could not open the audio file.\n"
            f"stderr:\n{tail}"
        )
    if "metal" in lower and "error" in lower:
        raise RuntimeError(
            "Metal GPU error in whisper.cpp.\n"
            "Try building without Metal:  cmake -DGGML_METAL=OFF ..\n"
            f"stderr:\n{tail}"
        )
    if "coreml" in lower and ("error" in lower or "failed" in lower):
        raise RuntimeError(
            "Core ML error.\n"
            "Ensure the *.mlmodelc bundle is present next to the .bin model\n"
            "and that SUBTITLER_WHISPER_CPP_USE_COREML matches your build.\n"
            f"stderr:\n{tail}"
        )
    raise RuntimeError(
        f"whisper.cpp exited with code {returncode}.\n"
        f"Binary: {binary}\n"
        f"stderr:\n{tail}"
    )
