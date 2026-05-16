import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    job_id: str
    filename: str
    language: str
    model: str
    engine: str
    status: str = "uploaded"
    progress: int = 0
    logs: list = field(default_factory=list)
    error: Optional[str] = None
    srt_path: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "language": self.language,
            "model": self.model,
            "engine": self.engine,
            "status": self.status,
            "progress": self.progress,
            "error": self.error,
            "srt_ready": self.srt_path is not None,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class JobStore:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)
            return job

    def log(self, job_id: str, message: str):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                ts = time.strftime("%H:%M:%S")
                job.logs.append(f"[{ts}] {message}")

    def get_logs(self, job_id: str, from_index: int = 0) -> list[str]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return []
            return job.logs[from_index:]

    def log_count(self, job_id: str) -> int:
        with self._lock:
            job = self._jobs.get(job_id)
            return len(job.logs) if job else 0


job_store = JobStore()
