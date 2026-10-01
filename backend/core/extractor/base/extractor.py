"""Common interface every platform adapter implements."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from core.config import Settings
from core.jobs.control import RunControl
from core.models import MediaFormat, MediaInfo, MediaItem
from core.security import SafeFetcher


@dataclass
class ExtractorContext:
    settings: Settings
    fetcher: SafeFetcher


class Extractor(ABC):
    """Add a platform by subclassing this and registering it; nothing else
    in the system needs to change."""

    platform: str
    hosts: tuple[str, ...]  # registrable domains (subdomains match)

    def __init__(self, ctx: ExtractorContext):
        self.ctx = ctx

    @abstractmethod
    async def analyze(self, url: str) -> MediaInfo:
        """Metadata + available items/formats. Must not download media."""

    @abstractmethod
    async def download(self, url: str, item: MediaItem, fmt: MediaFormat,
                       dest_dir: Path, ctl: RunControl) -> Path:
        """Fetch the chosen format into `dest_dir` and return the file path."""
