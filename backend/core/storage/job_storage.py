"""Per-job temporary directories with TTL cleanup and a disk quota."""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from core.errors import Busy, InvalidRequest
from core.security.filenames import confine

_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class JobStorage:
    def __init__(self, root: Path, quota_bytes: int):
        self.root = root
        self.quota = quota_bytes
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def job_dir(self, job_id: str) -> Path:
        if not _JOB_ID.match(job_id):
            raise InvalidRequest("Invalid job id.")
        return confine(self.root, self.root / job_id)

    def create(self, job_id: str) -> Path:
        if self.usage() > self.quota:
            raise Busy("Server storage is full. Try again later.")
        d = self.job_dir(job_id)
        d.mkdir(mode=0o700, exist_ok=False)
        return d

    def remove(self, job_id: str) -> None:
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def usage(self) -> int:
        total = 0
        for dirpath, _, files in os.walk(self.root):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    def purge_stale(self, older_than_seconds: float, keep: set[str] = frozenset()) -> int:
        """Delete job dirs not in `keep` whose mtime is older than the cutoff
        (used at startup and periodically for orphaned dirs)."""
        cutoff, removed = time.time() - older_than_seconds, 0
        for entry in self.root.iterdir():
            if entry.is_dir() and entry.name not in keep:
                try:
                    if entry.stat().st_mtime < cutoff:
                        shutil.rmtree(entry, ignore_errors=True)
                        removed += 1
                except OSError:
                    pass
        return removed
