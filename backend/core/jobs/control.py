"""Cooperative cancellation, deadline and progress for one running job."""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.errors import DownloadTimeout, JobCancelled

ProgressFn = Callable[[str, int, int | None], None]


class RunControl:
    """Thread-safe: yt-dlp progress hooks run in a worker thread."""

    def __init__(self, timeout: float, progress: ProgressFn | None = None):
        self.deadline = time.monotonic() + timeout
        self._cancel = threading.Event()
        self.progress = progress

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def cancel(self) -> None:
        self._cancel.set()

    def check(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()
        if time.monotonic() > self.deadline:
            raise DownloadTimeout()

    def remaining(self) -> float:
        return max(0.1, self.deadline - time.monotonic())

    def report(self, stage: str, done: int, total: int | None) -> None:
        self.check()
        if self.progress:
            self.progress(stage, done, total)
