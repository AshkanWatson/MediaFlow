"""Base adapter for sites handled by yt-dlp."""
from __future__ import annotations

from pathlib import Path

from core.errors import InvalidRequest, MediaNotFound
from core.extractor.base import Extractor, ExtractorContext
from core.extractor.common.ytdlp import YtDlpClient
from core.jobs.control import RunControl
from core.models import MediaFormat, MediaInfo, MediaItem, MediaKind
from core.security.url_guard import parse_url

_NONE = (None, "none")


def _https(u) -> str | None:
    return u if isinstance(u, str) and u.startswith("https://") else None


def _best_audio(item: MediaItem, prefer_ext: str | None = None) -> MediaFormat | None:
    audio = [f for f in item.formats if f.kind == MediaKind.AUDIO]
    if prefer_ext:
        pref = [f for f in audio if f.ext == prefer_ext]
        audio = pref or audio
    return audio[0] if audio else None  # formats are sorted best-first


def build_formats(raw_formats: list[dict]) -> list[MediaFormat]:
    """Collapse yt-dlp's format list into one entry per resolution (+ audio)."""
    video: dict[int, tuple[tuple, MediaFormat]] = {}
    audio: dict[str, tuple[float, MediaFormat]] = {}
    for f in raw_formats:
        fid, ext = str(f.get("format_id") or ""), f.get("ext") or "bin"
        if not fid or f.get("protocol") in ("mhtml",) or ext == "mhtml":
            continue
        size = f.get("filesize") or f.get("filesize_approx")
        v, a = f.get("vcodec") not in _NONE, f.get("acodec") not in _NONE
        if v:
            h = int(f.get("height") or 0)
            fmt = MediaFormat(id=fid, kind=MediaKind.VIDEO, ext=ext, height=h or None,
                              width=f.get("width"), fps=f.get("fps"), vcodec=f.get("vcodec"),
                              acodec=f.get("acodec") if a else None, filesize=size, has_audio=a,
                              label=f"{h}p {ext.upper()}" if h else ext.upper())
            # Prefer mp4/h264, then audio included, then bitrate.
            score = (ext == "mp4", str(f.get("vcodec", "")).startswith("avc"), a, f.get("tbr") or 0)
            if h not in video or score > video[h][0]:
                video[h] = (score, fmt)
        elif a:
            abr = f.get("abr") or f.get("tbr") or 0
            fmt = MediaFormat(id=fid, kind=MediaKind.AUDIO, ext=ext, acodec=f.get("acodec"),
                              filesize=size, has_audio=True, label=f"Audio {ext.upper()} {int(abr)}kbps")
            if ext not in audio or abr > audio[ext][0]:
                audio[ext] = (abr, fmt)
    out = [fmt for _, (_, fmt) in sorted(video.items(), key=lambda kv: -kv[0])]
    out += [fmt for _, fmt in sorted(audio.values(), key=lambda t: -t[0])]
    return out


class YtDlpExtractor(Extractor):
    allowed: tuple[str, ...]  # yt-dlp extractor key patterns

    def __init__(self, ctx: ExtractorContext, client: YtDlpClient | None = None):
        super().__init__(ctx)
        self.client = client or YtDlpClient(ctx.settings)

    def _item(self, info: dict, index: int | None) -> MediaItem:
        formats = build_formats(info.get("formats") or [])
        if not formats and (info.get("url") or info.get("ext")):
            # Single direct stream (e.g. an image) with no format table.
            ext = info.get("ext") or "bin"
            is_img = ext in ("jpg", "jpeg", "png", "webp")
            formats = [MediaFormat(id=str(info.get("format_id") or "best"),
                                   kind=MediaKind.IMAGE if is_img else MediaKind.VIDEO, ext=ext,
                                   height=info.get("height"), width=info.get("width"),
                                   filesize=info.get("filesize") or info.get("filesize_approx"),
                                   has_audio=not is_img, label=ext.upper())]
        kinds = {f.kind for f in formats}
        mtype = (MediaKind.VIDEO if MediaKind.VIDEO in kinds else
                 MediaKind.IMAGE if MediaKind.IMAGE in kinds else MediaKind.AUDIO)
        return MediaItem(id=str(info.get("id") or index or "1"), media_type=mtype,
                         title=info.get("title") or info.get("description"),
                         thumbnail=_https(info.get("thumbnail")), duration=info.get("duration"),
                         formats=formats, index=index)

    async def analyze(self, url: str) -> MediaInfo:
        raw = await self.client.extract_info(url, self.allowed)
        entries = raw.get("entries")
        if entries:
            items = [self._item(e, i) for i, e in enumerate((e for e in entries if e), 1)]
        else:
            items = [self._item(raw, None)]
        items = [i for i in items if i.formats]
        if not items:
            raise MediaNotFound("No downloadable media was found at this link.")
        first = items[0]
        return MediaInfo(platform=self.platform, url=url, title=raw.get("title") or first.title,
                         thumbnail=_https(raw.get("thumbnail")) or first.thumbnail,
                         duration=raw.get("duration") or first.duration, items=items)

    async def download(self, url: str, item: MediaItem, fmt: MediaFormat,
                       dest_dir: Path, ctl: RunControl) -> Path:
        parse_url(url)  # defence in depth: host re-validated at download time
        selector, merge_ext = fmt.id, "mp4"
        if fmt.kind == MediaKind.VIDEO and not fmt.has_audio:
            audio = _best_audio(item, "m4a" if fmt.ext == "mp4" else None)
            if audio is None:
                raise InvalidRequest("No audio stream available to merge.")
            selector = f"{fmt.id}+{audio.id}"
            merge_ext = "mp4" if fmt.ext == "mp4" and audio.ext == "m4a" else "mkv"
        return await self.client.download(url, selector, dest_dir, self.allowed, ctl,
                                          merge_ext=merge_ext, playlist_index=item.index)
