"""Background job queue: bounded concurrency, per-client limits, TTL cleanup."""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

from core.config import Settings
from core.errors import Busy, JobCancelled, JobNotFound, MediaFlowError
from core.jobs.control import RunControl
from core.models import DownloadRequest
from core.service import MediaService, ResultFile
from core.storage import JobStorage

log = logging.getLogger("mediaflow.jobs")
MAX_QUEUE = 50


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE = {JobState.QUEUED, JobState.RUNNING}


@dataclass
class Job:
    id: str
    client: str
    request: DownloadRequest
    ctl: RunControl
    state: JobState = JobState.QUEUED
    stage: str = "queued"
    done: int = 0
    total: int | None = None
    error: dict | None = None
    result: ResultFile | None = None
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    task: asyncio.Task | None = None

    def public(self) -> dict:
        pct = round(self.done * 100 / self.total, 1) if self.total else None
        return {"id": self.id, "state": self.state.value, "stage": self.stage,
                "bytes_done": self.done, "bytes_total": self.total, "percent": pct,
                "error": self.error,
                "file": {"name": self.result.filename, "size": self.result.size,
                         "content_type": self.result.content_type} if self.result else None}


class JobManager:
    def __init__(self, settings: Settings, service: MediaService, storage: JobStorage):
        self.s, self.service, self.storage = settings, service, storage
        self._jobs: dict[str, Job] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_jobs)
        self._sweeper: asyncio.Task | None = None

    # lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        self.storage.purge_stale(0)  # orphans from a previous run
        self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        for job in list(self._jobs.values()):
            if job.task:
                job.ctl.cancel()
                job.task.cancel()
        for jid in list(self._jobs):
            self.storage.remove(jid)
        self._jobs.clear()

    # API ---------------------------------------------------------------
    def create(self, req: DownloadRequest, client: str) -> Job:
        active = [j for j in self._jobs.values() if j.state in ACTIVE]
        if len(active) >= MAX_QUEUE:
            raise Busy()
        if sum(1 for j in active if j.client == client) >= self.s.max_active_jobs_per_client:
            raise Busy("You have too many downloads in progress. Wait for one to finish.")
        jid = secrets.token_urlsafe(24)
        job = Job(jid, client, req, RunControl(self.s.job_timeout_seconds, None))
        job.ctl.progress = lambda stage, d, t: self._on_progress(job, stage, d, t)
        self.storage.create(jid)
        self._jobs[jid] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    def get(self, job_id: str, client: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None or job.client != client:  # same error: don't leak existence
            raise JobNotFound()
        return job

    def cancel(self, job_id: str, client: str) -> None:
        job = self.get(job_id, client)
        job.ctl.cancel()
        if job.task and not job.task.done():
            return  # _run performs cleanup
        self._drop(job)

    # internals ---------------------------------------------------------
    @staticmethod
    def _on_progress(job: Job, stage: str, done: int, total: int | None) -> None:
        job.stage, job.done, job.total = stage, done, total

    async def _run(self, job: Job) -> None:
        try:
            async with self._sem:
                job.state = JobState.RUNNING
                job.ctl.deadline = time.monotonic() + self.s.job_timeout_seconds  # start clock after queueing
                job.result = await self.service.run(job.request, self.storage.job_dir(job.id), job.ctl)
                job.state, job.stage = JobState.READY, "ready"
        except JobCancelled:
            job.state, job.stage = JobState.CANCELLED, "cancelled"
        except asyncio.CancelledError:
            job.state = JobState.CANCELLED
            raise
        except MediaFlowError as e:
            job.state, job.stage, job.error = JobState.FAILED, "failed", e.to_dict()
        except Exception:  # never leak internals
            log.exception("job %s crashed", job.id)
            job.state, job.stage = JobState.FAILED, "failed"
            job.error = MediaFlowError().to_dict()
        finally:
            job.finished = time.monotonic()
            if job.state != JobState.READY:
                self.storage.remove(job.id)
            if job.ctl.cancelled:
                self._drop(job)

    def _drop(self, job: Job) -> None:
        self.storage.remove(job.id)
        self._jobs.pop(job.id, None)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            for job in list(self._jobs.values()):
                if job.finished and now - job.finished > self.s.job_ttl_seconds:
                    self._drop(job)
            self.storage.purge_stale(self.s.job_ttl_seconds * 2, keep=set(self._jobs))
