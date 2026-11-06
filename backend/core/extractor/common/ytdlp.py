"""yt-dlp integration shared by adapters that rely on it (YouTube, Instagram).

yt-dlp is used as a library (no shell). Only extractors named in
`allowed` may run, config files/cookies are ignored, and size/time limits are
enforced. Login-gated, private or DRM content is reported, never bypassed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, UnsupportedError

from core.config import Settings
from core.errors import (AuthRequired, MediaFlowError, MediaNotFound, RestrictedContent,
                         TooLarge, UnsupportedURL, UpstreamError)
from core.jobs.control import RunControl

_AUTH = ("sign in", "log in", "login", "private", "cookies", "authentication", "members-only",
         "not a bot", "rate-limit reached or login required")
_RESTRICTED = ("drm", "age", "geo", "country", "copyright", "blocked", "not available in your")
_NETWORK = ("unable to connect", "timed out", "connection", "proxy", "name or service", "temporary failure")
_MISSING = ("unavailable", "removed", "does not exist", "not found", "404", "deleted", "no video")


def map_ytdlp_error(exc: BaseException) -> MediaFlowError:
    if isinstance(exc, MediaFlowError):
        return exc
    # yt-dlp wraps errors raised from hooks; unwrap ours.
    inner = getattr(exc, "exc_info", None)
    if inner and isinstance(inner[1], MediaFlowError):
        return inner[1]
    if isinstance(exc, UnsupportedError):
        return UnsupportedURL()
    msg = str(exc).lower()
    if "no suitable extractor" in msg or "unsupported url" in msg:
        return UnsupportedURL()
    if any(k in msg for k in _NETWORK):
        return UpstreamError()
    if any(k in msg for k in _AUTH):
        return AuthRequired()
    if any(k in msg for k in _MISSING):
        return MediaNotFound()
    if any(k in msg for k in _RESTRICTED):
        return RestrictedContent()
    if "larger than max-filesize" in msg or "max-filesize" in msg:
        return TooLarge()
    return UpstreamError()


class YtDlpClient:
    def __init__(self, settings: Settings):
        self.s = settings

    def _base_opts(self, allowed: tuple[str, ...]) -> dict[str, Any]:
        return {
            "quiet": True, "no_warnings": True, "noprogress": True, "no_color": True,
            "ignoreconfig": True, "cachedir": False, "noplaylist": True,
            "allowed_extractors": list(allowed),
            "socket_timeout": self.s.read_timeout, "retries": 2, "fragment_retries": 2,
            "ffmpeg_location": self.s.ffmpeg_path if "/" in self.s.ffmpeg_path else None,
            "max_filesize": self.s.max_file_bytes,
            "concurrent_fragment_downloads": 2,
        }

    async def extract_info(self, url: str, allowed: tuple[str, ...]) -> dict:
        opts = self._base_opts(allowed)
        opts["skip_download"] = True
        opts["noplaylist"] = False  # carousels are returned as entries

        def run() -> dict:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return ydl.sanitize_info(info)

        try:
            return await asyncio.to_thread(run)
        except (DownloadError, ExtractorError, UnsupportedError) as e:
            raise map_ytdlp_error(e) from None

    async def download(self, url: str, selector: str, dest_dir: Path, allowed: tuple[str, ...],
                       ctl: RunControl, merge_ext: str = "mp4", playlist_index: int | None = None) -> Path:
        opts = self._base_opts(allowed)
        opts.update({
            "format": selector,
            "outtmpl": str(dest_dir / "media.%(ext)s"),
            "merge_output_format": merge_ext,
            "overwrites": True,
            "progress_hooks": [lambda d: self._hook(d, ctl)],
        })
        if playlist_index is not None:
            opts["noplaylist"] = False
            opts["playlist_items"] = str(playlist_index)

        def run() -> Path:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info.get("entries"):
                    info = next(iter(info["entries"]))
                dl = info.get("requested_downloads") or []
                path = Path(dl[0]["filepath"]) if dl else None
                if not path or not path.is_file():
                    raise UpstreamError("The download did not produce a file.")
                return path

        try:
            return await asyncio.to_thread(run)
        except (DownloadError, ExtractorError, UnsupportedError) as e:
            raise map_ytdlp_error(e) from None

    @staticmethod
    def _hook(d: dict, ctl: RunControl) -> None:
        if d.get("status") == "downloading":
            ctl.report("downloading", int(d.get("downloaded_bytes") or 0),
                       int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0) or None)
        else:
            ctl.check()
