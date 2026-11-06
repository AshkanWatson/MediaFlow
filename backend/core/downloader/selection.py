"""Pick the item/format a user asked for from a fresh analysis result."""
from __future__ import annotations

from core.errors import InvalidRequest, PreviewOnly
from core.models import DownloadRequest, MediaFormat, MediaInfo, MediaItem, MediaKind


def resolve_selection(info: MediaInfo, req: DownloadRequest) -> tuple[MediaItem, MediaFormat]:
    if req.item_id is not None:
        item = next((i for i in info.items if i.id == req.item_id), None)
        if item is None:
            raise InvalidRequest("Unknown item_id.")
    else:
        item = info.items[0]

    audio_out = req.output in ("mp3", "m4a")
    if req.format_id is not None:
        fmt = next((f for f in item.formats if f.id == req.format_id), None)
        if fmt is None:
            raise InvalidRequest("Unknown format_id. Re-run analyze and pick one of its formats.")
    else:  # default: best (formats are sorted best-first)
        want = MediaKind.AUDIO if audio_out else item.media_type
        fmt = next((f for f in item.formats if f.kind == want), None)
        if fmt is None:
            raise InvalidRequest("No matching format is available.")

    if audio_out:
        if fmt.kind == MediaKind.IMAGE:
            raise InvalidRequest("Audio output is not possible for images.")
        if fmt.kind == MediaKind.VIDEO:  # avoid downloading the video stream
            fmt = next((f for f in item.formats if f.kind == MediaKind.AUDIO), fmt)
    if fmt.is_preview and not req.accept_preview:
        raise PreviewOnly()
    return item, fmt
