from __future__ import annotations

import asyncio
import json
import shutil
import time
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.audio import AudioExtractionError, extract_audio
from app.config import settings
from app.jobs import Job, job_store
from app.subtitles.srt import segments_to_srt
from app.transcript import reconstruct_transcript
from app.transcribe.base import TranscriptionOptions
from app.transcribe.mlx_engine import MLXWhisperEngine
from app.transcribe.postprocess import detect_loop, strip_translation_segments
from app.transcribe.whisper_cpp_engine import WhisperCppEngine
from app.utils.files import cleanup_upload, save_upload, validate_upload

app = FastAPI(title="Subtitler", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ENGINES = {
    "mlx": MLXWhisperEngine(),
    "whisper_cpp": WhisperCppEngine(),
}


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup_check() -> None:
    if not shutil.which("ffmpeg"):
        import warnings
        warnings.warn(
            "FFmpeg not found. Jobs will fail at the audio-extraction step.\n"
            "Install with:  brew install ffmpeg",
            RuntimeWarning,
            stacklevel=1,
        )


# ---------------------------------------------------------------------------
# Background processing pipeline
# ---------------------------------------------------------------------------

async def _process_job(job_id: str, video_path: Path, opts: TranscriptionOptions) -> None:
    job = job_store.get(job_id)
    if not job:
        return

    try:
        # ── Step 1: Extract audio (pipe → RAM, no disk write) ─────────────
        job_store.update(job_id, status="extracting_audio", progress=5)
        job_store.log(job_id, f"Extracting audio from '{job.filename}' …")
        job_store.log(
            job_id,
            "Using FFmpeg pipe — audio is decoded in RAM, no WAV file written."
        )

        audio_array = await extract_audio(video_path)
        duration_s = len(audio_array) / 16_000
        job_store.log(
            job_id,
            f"Audio ready — {duration_s:.1f}s, "
            f"{len(audio_array) / 1e6:.1f} MB in RAM."
        )
        job_store.update(job_id, progress=20)

        # Clean up uploaded file as soon as audio is in RAM
        cleanup_upload(job_id)
        job_store.log(job_id, "Upload file removed.")

        # ── Step 2: Transcribe ────────────────────────────────────────────
        job_store.update(job_id, status="transcribing", progress=20)
        task_label = "translate → English" if opts.task == "translate" else "transcribe"
        lang_label = job.language if job.language != "auto" else "auto-detect"
        job_store.log(
            job_id,
            f"Starting — engine={job.engine}, model={job.model}, "
            f"language={lang_label}, task={task_label}"
        )
        if job.model in ("large-v3-turbo", "large-v3", "medium"):
            job_store.log(
                job_id,
                "First run: downloading model from HuggingFace (~1–3 GB). "
                "Subsequent runs use the local cache."
            )

        engine = _ENGINES.get(job.engine)
        if engine is None:
            raise ValueError(f"Unknown engine '{job.engine}'.")

        def _progress_cb(pct: int) -> None:
            mapped = 20 + int(pct * 0.65)
            job_store.update(job_id, progress=min(mapped, 85))

        segments = await asyncio.to_thread(
            engine.transcribe,
            audio_array,
            job.model,
            None if job.language == "auto" else job.language,
            opts,
            _progress_cb,
        )

        job_store.log(job_id, f"Transcription complete — {len(segments)} segments.")

        # ── Step 3: Repetition-loop detection ────────────────────────────
        focus_lang = None if job.language == "auto" else job.language
        clean_segments, loop_segments, loop_info = detect_loop(
            segments,
            max_run=settings.repetition_loop_max_run,
            min_fraction=settings.repetition_loop_min_fraction,
            focus_language=focus_lang,
        )

        output_dir = settings.storage_outputs / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 4: Generate SRT files ────────────────────────────────────
        job_store.update(job_id, status="generating_srt", progress=90)

        def _write_srt(segs: list, path: Path) -> None:
            content = segments_to_srt(
                [s.to_dict() for s in segs],
                max_chars=opts.max_line_chars,
                max_duration=opts.max_segment_duration,
                merge_gap_ms=opts.merge_gap_ms,
            )
            path.write_text(content, encoding="utf-8")

        # Always write the raw transcript (all segments, including any loop)
        raw_srt_path = output_dir / "raw_transcript.srt"
        _write_srt(segments, raw_srt_path)
        job_store.log(
            job_id,
            f"raw_transcript.srt written — {len(segments)} segments, "
            f"{raw_srt_path.stat().st_size / 1024:.1f} KB."
        )

        if loop_info:
            # Safe SRT excludes the loop — always generated alongside raw
            safe_srt_path = output_dir / "safe_transcript.srt"
            _write_srt(clean_segments, safe_srt_path)

            # Machine-readable postprocess report
            report = {
                "loop_detected": True,
                "repeated_text": loop_info.repeated_text,
                "loop_start_index": loop_info.loop_start_index,
                "loop_start_time_s": loop_info.loop_start_time,
                "segments_in_loop": loop_info.segment_count,
                "clean_segment_count": len(clean_segments),
                "focus_language": loop_info.focus_language,
            }
            (output_dir / "postprocess_report.json").write_text(
                json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
            )

            lang_label = loop_info.focus_language or "auto-detect"
            job_store.update(
                job_id,
                hallucination_warning=True,
                segments_dropped=loop_info.segment_count,
                loop_info=loop_info.to_dict(),
                raw_srt_path=str(raw_srt_path),
                safe_srt_path=str(safe_srt_path),
                srt_path=str(safe_srt_path),
            )
            job_store.log(
                job_id,
                f"⚠ Hallucination loop detected — focus language: {lang_label}, "
                f"loop starts at segment #{loop_info.loop_start_index + 1} "
                f"({loop_info.loop_start_time:.1f}s), repeated text: '{loop_info.repeated_text}', "
                f"{loop_info.segment_count} segments moved to raw_transcript.srt. "
                f"safe_transcript.srt contains {len(clean_segments)} clean segments.",
            )

            if not clean_segments:
                _fail(
                    job_id,
                    "The entire transcription was a repetition loop — no clean segments remain. "
                    "raw_transcript.srt contains the full output. "
                    "Try a different model or set a specific Focus language.",
                )
                return
        else:
            # No loop — raw IS the output
            job_store.update(
                job_id,
                raw_srt_path=str(raw_srt_path),
                srt_path=str(raw_srt_path),
            )

        # ── Step 5: Translation track filter (explicit opt-in only) ──────
        if opts.filter_translation_track:
            primary_lang = None if job.language == "auto" else job.language
            working_segs = clean_segments if loop_info else segments
            filtered_segs, n_filtered = strip_translation_segments(
                working_segs, primary_language=primary_lang
            )
            if n_filtered > 0:
                filtered_srt_path = output_dir / "filtered_transcript.srt"
                _write_srt(filtered_segs, filtered_srt_path)
                job_store.update(job_id, srt_path=str(filtered_srt_path))
                job_store.log(
                    job_id,
                    f"Translation filter: {n_filtered} interpreter segments removed "
                    f"({len(filtered_segs)} primary-language segments remain).",
                )
            else:
                job_store.log(job_id, "Translation filter: no secondary-language segments detected.")

        srt_path = Path(job_store.get(job_id).srt_path)
        size_kb = srt_path.stat().st_size / 1024
        job_store.log(job_id, f"Output SRT ready — {size_kb:.1f} KB.")
        job_store.update(
            job_id,
            status="completed",
            progress=100,
            completed_at=time.time(),
        )
        elapsed = time.time() - job_store.get(job_id).created_at
        job_store.log(job_id, f"Done in {elapsed:.0f}s. SRT is ready to download.")

    except AudioExtractionError as exc:
        _fail(job_id, str(exc))
    except NotImplementedError as exc:
        _fail(job_id, str(exc))
    except RuntimeError as exc:
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, f"Unexpected error: {exc}")


def _fail(job_id: str, error: str) -> None:
    job_store.update(job_id, status="failed", error=error, completed_at=time.time())
    job_store.log(job_id, f"FAILED: {error}")
    cleanup_upload(job_id)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.post("/api/jobs/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: str = Form(default="auto"),
    model: str = Form(default="large-v3-turbo"),
    engine: str = Form(default="mlx"),
    task: str = Form(default="transcribe"),
    max_line_chars: int = Form(default=42),
    max_segment_duration: float = Form(default=0.0),
    merge_gap_ms: int = Form(default=0),
    filter_translation_track: bool = Form(default=False),
):
    await validate_upload(file)

    if engine not in _ENGINES:
        raise HTTPException(400, f"Unknown engine '{engine}'. Available: {', '.join(_ENGINES)}")

    # Check engine availability before queuing work.
    ok, reason = _ENGINES[engine].is_available()
    if not ok:
        raise HTTPException(
            400,
            f"Engine '{engine}' is not available on this system:\n{reason}",
        )

    if model not in settings.mlx_model_repos:
        raise HTTPException(400, f"Unknown model '{model}'. Available: {', '.join(settings.mlx_model_repos)}")
    if task not in ("transcribe", "translate"):
        raise HTTPException(400, "task must be 'transcribe' or 'translate'.")
    if not (10 <= max_line_chars <= 84):
        raise HTTPException(400, "max_line_chars must be between 10 and 84.")
    if max_segment_duration < 0:
        raise HTTPException(400, "max_segment_duration must be ≥ 0.")
    if merge_gap_ms < 0:
        raise HTTPException(400, "merge_gap_ms must be ≥ 0.")

    opts = TranscriptionOptions(
        task=task,
        temperature=settings.default_temperature,
        condition_on_previous_text=settings.default_condition_on_previous,
        no_speech_threshold=settings.default_no_speech_threshold,
        compression_ratio_threshold=settings.default_compression_ratio_threshold,
        logprob_threshold=settings.default_logprob_threshold,
        filter_translation_track=filter_translation_track,
        max_line_chars=max_line_chars,
        max_segment_duration=max_segment_duration,
        merge_gap_ms=merge_gap_ms,
    )

    job_id = str(uuid.uuid4())
    video_path = await save_upload(file, job_id)

    job = Job(
        job_id=job_id,
        filename=file.filename or "upload",
        language=language,
        model=model,
        engine=engine,
    )
    job_store.create(job)
    job_store.log(job_id, f"Job created for '{file.filename}'.")

    background_tasks.add_task(_process_job, job_id, video_path, opts)
    return {"job_id": job_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/logs")
async def job_logs(job_id: str):
    """Server-Sent Events stream delivering logs and status in real time."""
    if not job_store.get(job_id):
        raise HTTPException(404, "Job not found.")

    async def _stream():
        last_idx = 0
        while True:
            job = job_store.get(job_id)
            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Job not found'})}\n\n"
                return

            new_logs = job_store.get_logs(job_id, from_index=last_idx)
            for msg in new_logs:
                yield f"data: {json.dumps({'type': 'log', 'message': msg})}\n\n"
            last_idx += len(new_logs)

            yield f"data: {json.dumps({'type': 'status', 'status': job.status, 'progress': job.progress})}\n\n"

            if job.status in ("completed", "failed"):
                yield f"data: {json.dumps({'type': 'done', 'status': job.status, 'hallucination_warning': job.hallucination_warning, 'segments_dropped': job.segments_dropped, 'loop_info': job.loop_info})}\n\n"
                return

            await asyncio.sleep(0.1)  # 100 ms poll — logs feel instantaneous

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/transcript")
async def start_transcript(job_id: str, background_tasks: BackgroundTasks):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.status != "completed" or not job.srt_path:
        raise HTTPException(400, "SRT must be completed before generating a transcript.")
    if job.transcript_status == "generating":
        raise HTTPException(409, "Transcript generation already in progress.")
    job_store.update(job_id, transcript_status="generating")
    background_tasks.add_task(_generate_transcript, job_id)
    return {"status": "generating"}


async def _generate_transcript(job_id: str) -> None:
    job = job_store.get(job_id)
    if not job or not job.srt_path:
        return
    try:
        srt_content = Path(job.srt_path).read_text(encoding="utf-8")
        transcript = await asyncio.to_thread(reconstruct_transcript, srt_content)
        transcript_path = Path(job.srt_path).parent / "transcript.md"
        transcript_path.write_text(transcript, encoding="utf-8")
        job_store.update(job_id, transcript_status="ready", transcript_path=str(transcript_path))
    except Exception as exc:  # noqa: BLE001
        job_store.update(job_id, transcript_status="failed", error=str(exc))


@app.get("/api/jobs/{job_id}/download-transcript")
async def download_transcript(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.transcript_status != "ready" or not job.transcript_path:
        raise HTTPException(400, "Transcript is not ready yet.")
    transcript_path = Path(job.transcript_path)
    if not transcript_path.exists():
        raise HTTPException(500, "Transcript file is missing from disk.")
    safe_stem = Path(job.filename).stem[:80]
    return FileResponse(
        path=transcript_path,
        media_type="text/markdown; charset=utf-8",
        filename=f"{safe_stem}-transcript.md",
    )


@app.get("/api/jobs/{job_id}/download-srt")
async def download_srt(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.status != "completed" or not job.srt_path:
        raise HTTPException(400, "SRT is not ready yet.")

    srt_path = Path(job.srt_path)
    if not srt_path.exists():
        raise HTTPException(500, "SRT file is missing from disk.")

    safe_stem = Path(job.filename).stem[:80]
    return FileResponse(
        path=srt_path,
        media_type="text/plain; charset=utf-8",
        filename=f"{safe_stem}.srt",
    )


@app.get("/api/jobs/{job_id}/download-raw-srt")
async def download_raw_srt(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if not job.raw_srt_path:
        raise HTTPException(400, "Raw SRT is not ready yet.")
    raw_path = Path(job.raw_srt_path)
    if not raw_path.exists():
        raise HTTPException(500, "Raw SRT file is missing from disk.")
    safe_stem = Path(job.filename).stem[:80]
    return FileResponse(
        path=raw_path,
        media_type="text/plain; charset=utf-8",
        filename=f"{safe_stem}-raw.srt",
    )


@app.get("/api/config")
async def get_config():
    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    engine_status = {
        name: {"available": ok, "reason": reason}
        for name, engine in _ENGINES.items()
        for ok, reason in [engine.is_available()]
    }
    return {
        "models": list(settings.mlx_model_repos.keys()),
        "languages": settings.supported_languages,
        "engines": engine_status,
        "defaults": {
            "model": settings.default_model,
            "language": settings.default_language,
            "engine": settings.default_engine,
            "task": settings.default_task,
            "max_line_chars": settings.default_max_line_chars,
            "max_segment_duration": settings.default_max_segment_duration,
            "merge_gap_ms": settings.default_merge_gap_ms,
        },
        "anti_hallucination": {
            "compression_ratio_threshold": settings.default_compression_ratio_threshold,
            "logprob_threshold": settings.default_logprob_threshold,
            "repetition_loop_max_run": settings.repetition_loop_max_run,
        },
        "system": {
            "ffmpeg_available": ffmpeg_ok,
            "ffmpeg_warning": None if ffmpeg_ok else (
                "FFmpeg is not installed. Run: brew install ffmpeg"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Serve built frontend (production)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
