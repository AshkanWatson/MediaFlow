"""Platform-independent data model returned by extractors and the API."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MediaKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"


class MediaFormat(BaseModel):
    id: str
    kind: MediaKind
    ext: str
    label: str = ""
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    has_audio: bool = False
    is_preview: bool = False
    # Set for direct-URL extractors; never exposed through the API.
    url: str | None = Field(default=None, exclude=True)


class MediaItem(BaseModel):
    id: str
    media_type: MediaKind
    title: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    formats: list[MediaFormat] = []
    # 1-based playlist index for multi-item sources (carousels).
    index: int | None = Field(default=None, exclude=True)


class MediaInfo(BaseModel):
    platform: str
    url: str
    title: str | None = None
    thumbnail: str | None = None
    duration: float | None = None
    notes: list[str] = []
    items: list[MediaItem]


OUTPUT_FORMATS = ("original", "mp3", "m4a")


class DownloadRequest(BaseModel):
    url: str
    item_id: str | None = None
    format_id: str | None = None
    output: str = "original"
    accept_preview: bool = False
