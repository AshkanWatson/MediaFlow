"""HTTP API (FastAPI). Thin layer: validation, auth, rate limiting, serialisation."""
from __future__ import annotations

import asyncio
import hmac
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.config import Settings
from core.errors import InvalidRequest, MediaFlowError, Unauthorized
from core.jobs.manager import JobManager, JobState
from core.models import OUTPUT_FORMATS, DownloadRequest
from core.security import RateLimiter
from core.service import MediaService
from core.storage import JobStorage


class AnalyzeBody(BaseModel):
    url: str = Field(max_length=2048)


class JobBody(DownloadRequest):
    url: str = Field(max_length=2048)
    item_id: str | None = Field(default=None, max_length=64)
    format_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.\-+]+$")


def create_app(settings: Settings | None = None, service: MediaService | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    svc = service or MediaService(s)
    storage = JobStorage(s.work_dir, s.work_dir_quota_bytes)
    jobs = JobManager(s, svc, storage)
    limiter = RateLimiter(s.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await jobs.start()
        yield
        await jobs.stop()
        await svc.aclose()

    app = FastAPI(title="MediaFlow", version="1.0.0", lifespan=lifespan,
                  docs_url="/docs", redoc_url=None)
    app.state.jobs, app.state.service = jobs, svc
    if s.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins),
                           allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

    @app.exception_handler(MediaFlowError)
    async def _mf(_: Request, exc: MediaFlowError):
        return JSONResponse({"error": exc.to_dict()}, status_code=exc.http_status)

    def client_id(request: Request) -> str:
        # Behind a reverse proxy, configure uvicorn --proxy-headers so this is the real client.
        return request.client.host if request.client else "unknown"

    async def guard(request: Request) -> str:
        if s.api_key:
            supplied = request.headers.get("x-api-key", "")
            if not hmac.compare_digest(supplied.encode(), s.api_key.encode()):
                raise Unauthorized()
        cid = client_id(request)
        limiter.check(cid)
        return cid

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "platforms": svc.registry.platforms}

    @app.post("/v1/analyze")
    async def analyze(body: AnalyzeBody, _: str = Depends(guard)):
        return (await svc.analyze(body.url)).model_dump(mode="json")

    @app.post("/v1/jobs", status_code=202)
    async def create_job(body: JobBody, cid: str = Depends(guard)):
        if body.output not in OUTPUT_FORMATS:
            raise InvalidRequest(f"output must be one of {', '.join(OUTPUT_FORMATS)}.")
        return jobs.create(DownloadRequest(**body.model_dump()), cid).public()

    @app.get("/v1/jobs/{job_id}")
    async def get_job(job_id: str, cid: str = Depends(guard)):
        return jobs.get(job_id, cid).public()

    @app.get("/v1/jobs/{job_id}/events")
    async def job_events(job_id: str, cid: str = Depends(guard)):
        job = jobs.get(job_id, cid)

        async def gen():
            last = None
            while True:
                snap = json.dumps(job.public())
                if snap != last:
                    yield f"data: {snap}\n\n"
                    last = snap
                if job.state not in (JobState.QUEUED, JobState.RUNNING):
                    return
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/v1/jobs/{job_id}/file")
    async def get_file(job_id: str, cid: str = Depends(guard)):
        job = jobs.get(job_id, cid)
        if job.state != JobState.READY or job.result is None:
            raise InvalidRequest("The file is not ready.")
        r = job.result
        return FileResponse(r.path, media_type=r.content_type, filename=r.filename,
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})

    @app.delete("/v1/jobs/{job_id}", status_code=204)
    async def delete_job(job_id: str, cid: str = Depends(guard)):
        jobs.cancel(job_id, cid)

    return app
