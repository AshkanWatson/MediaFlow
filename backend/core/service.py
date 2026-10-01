"""Central pipeline:
URL → validate → detect platform → extract metadata → select media →
download → process/validate → (temporary storage owned by the job layer)."""
from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings
from core.downloader import resolve_selection
from core.errors import DownloadTimeout
from core.extractor import ExtractorContext, build_registry
from core.jobs.control import RunControl
from core.models import DownloadRequest, MediaInfo, MediaKind
from core.processor import Processor
from core.security import SafeFetcher, parse_url, sanitize_filename

ANALYZE_TIMEOUT = 60

# Defined here so the API never guesses a type from user-influenced data.
CONTENT_TYPES = {"mp4": "video/mp4", "mkv": "video/x-matroska", "webm": "video/webm",
                 "mp3": "audio/mpeg", "m4a": "audio/mp4", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                 "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


@dataclass
class ResultFile:
    path: Path
    filename: str
    content_type: str
    size: int


class MediaService:
    def __init__(self, settings: Settings, fetcher: SafeFetcher | None = None):
        self.s = settings
        self.fetcher = fetcher or SafeFetcher(settings)
        self.registry = build_registry(ExtractorContext(settings, self.fetcher))
        self.processor = Processor(settings)

    async def aclose(self) -> None:
        await self.fetcher.aclose()

    async def analyze(self, url: str) -> MediaInfo:
        parsed = parse_url(url, self.s.allowed_ports)
        extractor = self.registry.detect(parsed)
        try:
            return await asyncio.wait_for(extractor.analyze(parsed.url), ANALYZE_TIMEOUT)
        except asyncio.TimeoutError:
            raise DownloadTimeout() from None

    async def run(self, req: DownloadRequest, job_dir: Path, ctl: RunControl) -> ResultFile:
        parsed = parse_url(req.url, self.s.allowed_ports)
        extractor = self.registry.detect(parsed)
        ctl.report("analyzing", 0, None)
        info = await extractor.analyze(parsed.url)
        item, fmt = resolve_selection(info, req)
        ctl.check()

        path = await extractor.download(parsed.url, item, fmt, job_dir, ctl)
        ctl.report("processing", 0, None)
        if fmt.kind == MediaKind.IMAGE:
            self.processor.validate_image(path)
        else:
            await self.processor.validate_av(path)
            if req.output in ("mp3", "m4a"):
                path = await self.processor.extract_audio(path, job_dir, req.output)
                await self.processor.validate_av(path)
        ext = path.suffix.lstrip(".").lower()
        ctype = CONTENT_TYPES.get(ext) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        name = sanitize_filename(item.title or info.title, ext, fallback=info.platform.lower())
        return ResultFile(path, name, ctype, path.stat().st_size)
