"""Runtime configuration (environment variables, safe defaults)."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

GB = 1024**3


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    work_dir: Path = Path(tempfile.gettempdir()) / "mediaflow"
    api_key: str | None = None
    cors_origins: tuple[str, ...] = ()
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    max_file_bytes: int = 2 * GB
    max_page_bytes: int = 2 * 1024 * 1024
    max_image_pixels: int = 100_000_000
    max_duration_seconds: int = 4 * 3600
    job_timeout_seconds: int = 900
    ffmpeg_timeout_seconds: int = 600
    max_concurrent_jobs: int = 3
    max_active_jobs_per_client: int = 3
    job_ttl_seconds: int = 1800
    work_dir_quota_bytes: int = 20 * GB
    rate_limit_per_minute: int = 30
    max_redirects: int = 5
    connect_timeout: float = 10.0
    read_timeout: float = 20.0
    user_agent: str = "MediaFlow/1.0 (+https://github.com/AshkanWatson/MediaFlow)"
    allowed_ports: frozenset[int] = field(default_factory=lambda: frozenset({80, 443}))

    @classmethod
    def from_env(cls) -> "Settings":
        d = cls()
        origins = tuple(
            o.strip() for o in os.environ.get("MEDIAFLOW_CORS_ORIGINS", "").split(",") if o.strip()
        )
        return cls(
            work_dir=Path(os.environ.get("MEDIAFLOW_WORK_DIR", str(d.work_dir))),
            api_key=os.environ.get("MEDIAFLOW_API_KEY") or None,
            cors_origins=origins,
            ffmpeg_path=os.environ.get("MEDIAFLOW_FFMPEG", d.ffmpeg_path),
            ffprobe_path=os.environ.get("MEDIAFLOW_FFPROBE", d.ffprobe_path),
            max_file_bytes=_int("MEDIAFLOW_MAX_FILE_BYTES", d.max_file_bytes),
            job_timeout_seconds=_int("MEDIAFLOW_JOB_TIMEOUT", d.job_timeout_seconds),
            max_concurrent_jobs=_int("MEDIAFLOW_MAX_CONCURRENT_JOBS", d.max_concurrent_jobs),
            max_active_jobs_per_client=_int("MEDIAFLOW_MAX_JOBS_PER_CLIENT", d.max_active_jobs_per_client),
            job_ttl_seconds=_int("MEDIAFLOW_JOB_TTL", d.job_ttl_seconds),
            rate_limit_per_minute=_int("MEDIAFLOW_RATE_LIMIT", d.rate_limit_per_minute),
        )
