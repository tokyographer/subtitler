import re
import shutil
from pathlib import Path

import filetype
from fastapi import HTTPException, UploadFile

from app.config import settings


_SAFE_FILENAME_RE = re.compile(r"[^\w.\-]")
_MAX_FILENAME_LEN = 200


def secure_filename(name: str) -> str:
    """Sanitise a filename: strip directory components and dangerous chars."""
    name = Path(name).name  # strip any path components
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.lstrip(".")  # no hidden files
    if not name:
        name = "upload"
    return name[:_MAX_FILENAME_LEN]


async def validate_upload(file: UploadFile) -> None:
    """Raise HTTPException for invalid file type or missing filename."""
    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            400,
            f"Extension '{ext}' is not allowed. "
            f"Accepted: {', '.join(sorted(settings.allowed_extensions))}",
        )

    # Check magic bytes (first 2 KB is enough for all major video formats)
    chunk = await file.read(2048)
    await file.seek(0)

    kind = filetype.guess(chunk)
    if kind is not None:
        mime = kind.mime
        if not any(mime.startswith(p) for p in settings.allowed_mime_prefixes):
            raise HTTPException(
                400,
                f"File content type '{mime}' is not a recognised video format.",
            )


async def save_upload(file: UploadFile, job_id: str) -> Path:
    """
    Stream the upload into storage/uploads/<job_id>/<safe_name>.
    Enforces the max file size limit.
    Raises HTTPException(413) if the file is too large.
    """
    upload_dir = settings.storage_uploads / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file.filename or "upload")
    file_path = upload_dir / safe_name

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    total = 0

    try:
        with open(file_path, "wb") as fh:
            while True:
                chunk = await file.read(1 * 1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fh.close()
                    shutil.rmtree(upload_dir, ignore_errors=True)
                    raise HTTPException(
                        413,
                        f"File exceeds the {settings.max_file_size_mb} MB limit.",
                    )
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(500, f"Failed to save upload: {exc}") from exc

    return file_path


def cleanup_job_files(job_id: str) -> None:
    """Remove all temporary files for a job (upload + audio). Keep the SRT."""
    for base in (settings.storage_uploads, settings.storage_audio):
        job_dir = base / job_id
        if job_dir.exists():
            shutil.rmtree(job_dir, ignore_errors=True)
