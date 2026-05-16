from __future__ import annotations

import asyncio
import json
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
from app.transcribe.mlx_engine import MLXWhisperEngine
from app.transcribe.whisper_cpp_engine import WhisperCppEngine
from app.utils.files import cleanup_job_files, save_upload, validate_upload

app = FastAPI(title="Subtitler", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ENGINES = {
    "mlx": MLXWhisperEngine(),
    "whisper_cpp": WhisperCppEngine(),
}


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

async def _process_job(job_id: str, video_path: Path) -> None:
    job = job_store.get(job_id)
    if not job:
        return

    try:
        # ── Step 1: Extract audio ─────────────────────────────────────────
        job_store.update(job_id, status="extracting_audio", progress=5)
        job_store.log(job_id, f"Extracting audio from '{job.filename}' …")

        audio_dir = settings.storage_audio / job_id
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / "audio.wav"

        await extract_audio(video_path, audio_path)
        job_store.update(job_id, progress=20)
        job_store.log(job_id, "Audio extracted (16 kHz mono WAV).")

        # ── Step 2: Transcribe ────────────────────────────────────────────
        job_store.update(job_id, status="transcribing", progress=20)
        lang_label = job.language if job.language != "auto" else "auto-detect"
        job_store.log(
            job_id,
            f"Starting transcription — engine={job.engine}, "
            f"model={job.model}, language={lang_label}",
        )
        job_store.log(
            job_id,
            "Note: first run downloads the model from HuggingFace (~few GB). "
            "Subsequent runs use the local cache.",
        )

        engine = _ENGINES.get(job.engine)
        if engine is None:
            raise ValueError(f"Unknown engine '{job.engine}'.")

        def _progress_cb(pct: int) -> None:
            # Map transcription progress (0-100) → overall 20-85%
            mapped = 20 + int(pct * 0.65)
            job_store.update(job_id, progress=min(mapped, 85))

        segments = await asyncio.to_thread(
            engine.transcribe,
            audio_path,
            job.model,
            None if job.language == "auto" else job.language,
            _progress_cb,
        )

        job_store.log(job_id, f"Transcription complete — {len(segments)} segments found.")

        # ── Step 3: Generate SRT ──────────────────────────────────────────
        job_store.update(job_id, status="generating_srt", progress=90)
        job_store.log(job_id, "Generating SRT file …")

        output_dir = settings.storage_outputs / job_id
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = output_dir / "output.srt"

        srt_content = segments_to_srt([s.to_dict() for s in segments])
        srt_path.write_text(srt_content, encoding="utf-8")

        job_store.log(job_id, f"SRT written ({srt_path.stat().st_size} bytes).")

        # ── Cleanup temp files ────────────────────────────────────────────
        cleanup_job_files(job_id)
        job_store.log(job_id, "Temporary files cleaned up.")

        import time
        job_store.update(
            job_id,
            status="completed",
            progress=100,
            srt_path=str(srt_path),
            completed_at=time.time(),
        )
        job_store.log(job_id, "Done! Your SRT file is ready for download.")

    except AudioExtractionError as exc:
        _fail(job_id, f"Audio extraction failed: {exc}")
    except NotImplementedError as exc:
        _fail(job_id, str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, f"Unexpected error: {exc}")


def _fail(job_id: str, error: str) -> None:
    import time
    job_store.update(job_id, status="failed", error=error, completed_at=time.time())
    job_store.log(job_id, f"ERROR: {error}")
    cleanup_job_files(job_id)


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
):
    await validate_upload(file)

    if engine not in _ENGINES:
        raise HTTPException(400, f"Unknown engine '{engine}'. Available: {', '.join(_ENGINES)}")

    if model not in settings.mlx_model_repos:
        raise HTTPException(
            400,
            f"Unknown model '{model}'. Available: {', '.join(settings.mlx_model_repos)}",
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

    background_tasks.add_task(_process_job, job_id, video_path)

    return {"job_id": job_id, "status": job.status}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/logs")
async def job_logs(job_id: str):
    """Server-Sent Events stream of logs and status updates."""
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

            yield (
                f"data: {json.dumps({'type': 'status', 'status': job.status, 'progress': job.progress})}\n\n"
            )

            if job.status in ("completed", "failed"):
                yield f"data: {json.dumps({'type': 'done', 'status': job.status})}\n\n"
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/download-srt")
async def download_srt(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.status != "completed" or not job.srt_path:
        raise HTTPException(400, "SRT file is not ready yet.")

    srt_path = Path(job.srt_path)
    if not srt_path.exists():
        raise HTTPException(500, "SRT file missing from disk.")

    safe_stem = Path(job.filename).stem[:80]
    return FileResponse(
        path=srt_path,
        media_type="text/plain; charset=utf-8",
        filename=f"{safe_stem}.srt",
    )


@app.get("/api/config")
async def get_config():
    return {
        "models": list(settings.mlx_model_repos.keys()),
        "languages": settings.supported_languages,
        "engines": list(_ENGINES.keys()),
        "defaults": {
            "model": settings.default_model,
            "language": settings.default_language,
            "engine": settings.default_engine,
        },
    }


# ---------------------------------------------------------------------------
# Serve built frontend (production)
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
