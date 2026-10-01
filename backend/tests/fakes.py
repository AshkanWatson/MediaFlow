"""Canned yt-dlp results / fetchers for adapter tests (no network)."""
from pathlib import Path

from core.extractor.base import ExtractorContext
from core.security.safe_fetcher import FetchResponse

import httpx

YT_INFO = {
    "id": "abc123", "title": "Test Video", "thumbnail": "https://i.ytimg.com/vi/abc/hq.jpg", "duration": 61,
    "formats": [
        {"format_id": "sb0", "ext": "mhtml", "vcodec": "none", "acodec": "none", "protocol": "mhtml"},
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1.42001E", "acodec": "mp4a.40.2", "height": 360, "width": 640, "tbr": 500},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "none", "height": 1080, "width": 1920, "fps": 30, "tbr": 4000, "filesize": 5_000_000},
        {"format_id": "248", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 1080, "tbr": 2500},
        {"format_id": "136", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "none", "height": 720, "tbr": 2000},
        {"format_id": "313", "ext": "webm", "vcodec": "vp9", "acodec": "none", "height": 2160, "tbr": 9000},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 129, "filesize": 900_000},
        {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus", "abr": 135},
    ],
}

IG_CAROUSEL = {
    "id": "post1", "title": "Carousel", "thumbnail": "https://scontent.cdninstagram.com/t.jpg",
    "_type": "playlist",
    "entries": [
        {"id": "e1", "title": "Video 1", "ext": "mp4", "url": "https://x/v.mp4", "format_id": "0", "duration": 5,
         "formats": [{"format_id": "0", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 1080}]},
        {"id": "e2", "title": "Image 2", "ext": "jpg", "url": "https://x/i.jpg", "format_id": "0"},
    ],
}


class FakeYtDlp:
    def __init__(self, info):
        self.info, self.calls = info, []

    async def extract_info(self, url, allowed):
        self.calls.append(("extract", url, allowed))
        return self.info

    async def download(self, url, selector, dest_dir, allowed, ctl, merge_ext="mp4", playlist_index=None):
        self.calls.append(("download", selector, merge_ext, playlist_index, allowed))
        p = Path(dest_dir) / f"media.{merge_ext}"
        p.write_bytes(b"x")
        return p


class FakeFetcher:
    def __init__(self, pages=None, files=None):
        self.pages, self.files, self.downloads = pages or {}, files or {}, []

    async def aclose(self):
        pass

    async def get_bytes(self, url, max_bytes=None, accept="*/*"):
        status, body = self.pages[url]
        return FetchResponse(url, status, httpx.Headers({"content-type": "text/html"}), body.encode())

    async def download_to(self, url, dest, max_bytes, deadline=None, progress=None, check=None, accept="*/*"):
        ctype, data = self.files[url]
        dest.write_bytes(data)
        self.downloads.append(url)
        return httpx.Headers({"content-type": ctype})


def ctx(settings, fetcher=None):
    return ExtractorContext(settings, fetcher or FakeFetcher())
