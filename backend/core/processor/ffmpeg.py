"""FFmpeg/ffprobe wrapper. Arguments come only from fixed templates; user input
never reaches a command line (no shell, no user-controlled paths/options)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.config import Settings
from core.errors import InvalidMedia, ProcessingFailed, DownloadTimeout, TooLarge
from core.security.filenames import confine

AUDIO_PRESETS = {
    "mp3": ("mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "m4a": ("m4a", ["-c:a", "aac", "-b:a", "192k"]),
}
ALLOWED_VIDEO_CONTAINERS = {"mp3", "mov", "mp4", "m4a", "matroska", "webm", "avi", "flv", "mpegts", "ogg"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
_BASE = ["-nostdin", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "file"]


class Processor:
    def __init__(self, settings: Settings):
        self.s = settings

    async def _run(self, argv: list[str], timeout: float) -> bytes:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise DownloadTimeout() from None
        except BaseException:
            proc.kill()
            raise
        if proc.returncode != 0:
            raise ProcessingFailed() from RuntimeError(err.decode("utf-8", "replace")[:500])
        return out

    async def probe(self, path: Path) -> dict:
        out = await self._run(
            [self.s.ffprobe_path, "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", "-protocol_whitelist", "file", str(path)],
            timeout=60,
        )
        try:
            return json.loads(out)
        except ValueError:
            raise InvalidMedia() from None

    async def validate_av(self, path: Path) -> dict:
        """Reject files ffprobe can't parse, unexpected containers, excess duration/size."""
        if path.stat().st_size > self.s.max_file_bytes:
            raise TooLarge()
        try:
            info = await self.probe(path)
        except ProcessingFailed:
            raise InvalidMedia() from None
        fmt = info.get("format", {})
        names = set(str(fmt.get("format_name", "")).split(","))
        if not names & ALLOWED_VIDEO_CONTAINERS or not info.get("streams"):
            raise InvalidMedia()
        if float(fmt.get("duration") or 0) > self.s.max_duration_seconds:
            raise InvalidMedia("The media is longer than the allowed maximum.")
        return info

    def validate_image(self, path: Path) -> str:
        from PIL import Image, UnidentifiedImageError

        Image.MAX_IMAGE_PIXELS = self.s.max_image_pixels
        try:
            with Image.open(path) as im:
                fmt = im.format
                if fmt not in ALLOWED_IMAGE_FORMATS:
                    raise InvalidMedia()
                if im.width * im.height > self.s.max_image_pixels:
                    raise InvalidMedia("Image dimensions are too large.")
                im.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError):
            raise InvalidMedia() from None
        return fmt.lower()

    async def extract_audio(self, src: Path, job_dir: Path, fmt: str) -> Path:
        if fmt not in AUDIO_PRESETS:
            raise ProcessingFailed("Unsupported audio format.")
        ext, codec_args = AUDIO_PRESETS[fmt]
        src, dst = confine(job_dir, src), confine(job_dir, job_dir / f"audio.{ext}")
        argv = [self.s.ffmpeg_path, *_BASE, "-y", "-i", str(src), "-vn", "-map", "0:a:0",
                *codec_args, "-fs", str(self.s.max_file_bytes), str(dst)]
        await self._run(argv, self.s.ffmpeg_timeout_seconds)
        return dst
