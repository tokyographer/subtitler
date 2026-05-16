import re
import shutil
from pathlib import Path

import filetype
from fastapi import HTTPException, UploadFile

from app.config import settings


_SAFE_FILENAME_RE = re.compile(r"[^\w.\-]")
_MAX_FILENAME_LEN = 200


def secure_filename(name: str) -> str:
    name = Path(name).name
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.lstrip(".")
    return (name or "upload")[:_MAX_FILENAME_LEN]


async def validate_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(400, "No filename provided.")

    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            400,
            f"File type '{ext}' is not supported.\n"
            f"Accepted formats: {', '.join(sorted(settings.allowed_extensions))}",
        )

    chunk = await file.read(2048)
    await file.seek(0)

    kind = filetype.guess(chunk)
    if kind is not None:
        if not any(kind.mime.startswith(p) for p in settings.allowed_mime_prefixes):
            raise HTTPException(
                400,
                f"File content does not appear to be a video or audio file "
                f"(detected: {kind.mime}).",
            )


async def save_upload(file: UploadFile, job_id: str) -> Path:
    upload_dir = settings.storage_uploads / job_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file.filename or "upload")
    file_path = upload_dir / safe_name
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    total = 0

    try:
        with open(file_path, "wb") as fh:
            while True:
                chunk = await file.read(1 * 1024 * 1024)
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


def cleanup_upload(job_id: str) -> None:
    """Remove the uploaded source file. The SRT output is kept."""
    job_dir = settings.storage_uploads / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
