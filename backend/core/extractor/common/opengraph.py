"""Public page metadata (OpenGraph / Twitter cards / JSON-LD) extraction.

Used for sites that publish only a public preview. Pure parsing, stdlib only.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

from core.errors import (AuthRequired, InvalidMedia, InvalidRequest, MediaNotFound, RestrictedContent,
                         UnsupportedURL, UpstreamError)
from core.extractor.base import Extractor
from core.jobs.control import RunControl
from core.models import MediaFormat, MediaInfo, MediaItem, MediaKind

EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
               "video/mp4": "mp4", "video/webm": "webm"}
_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|mp4|webm)(?:$|[?#])", re.I)


class _MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, list[str]] = {}
        self.jsonld: list[str] = []
        self._in_ld = False
        self._title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, []).append(a["content"].strip())
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self.jsonld.append("")
        elif tag == "title":
            self._title = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_ld = False
        elif tag == "title":
            self._title = False

    def handle_data(self, data):
        if self._in_ld:
            self.jsonld[-1] += data
        elif self._title:
            self.title += data


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def parse_page(html: str, base_url: str) -> dict:
    p = _MetaParser()
    p.feed(html[:2_000_000])
    first = lambda *keys: next((p.meta[k][0] for k in keys if p.meta.get(k)), None)
    images = [first("og:image:secure_url", "og:image", "twitter:image")]
    videos = [first("og:video:secure_url", "og:video", "og:video:url", "twitter:player:stream")]
    title = first("og:title", "twitter:title") or p.title.strip() or None
    for raw in p.jsonld:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for n in _walk(data):
            t = n.get("@type")
            if t in ("ImageObject", ["ImageObject"]) and isinstance(n.get("contentUrl"), str):
                images.insert(0, n["contentUrl"])
            elif t in ("VideoObject", ["VideoObject"]) and isinstance(n.get("contentUrl"), str):
                videos.insert(0, n["contentUrl"])
            if not title and isinstance(n.get("name"), str):
                title = n["name"]
    absolute = lambda u: urljoin(base_url, u) if u else None
    return {
        "title": title,
        "description": first("og:description", "description"),
        "images": [u for u in map(absolute, images) if u and u.startswith("https://")],
        "videos": [u for u in map(absolute, videos) if u and u.startswith("https://")],
        "login_wall": bool(re.search(r"(sign in|log in|captcha|are you a robot)", p.title, re.I)),
    }


class OpenGraphExtractor(Extractor):
    """Reads publicly served preview media for stock sites. Every asset is
    flagged `is_preview`; MediaFlow never removes watermarks or fetches
    licensed originals (those need an account/licence)."""

    preview_note: str = ""

    async def analyze(self, url: str) -> MediaInfo:
        resp = await self.ctx.fetcher.get_bytes(url, accept="text/html,application/xhtml+xml")
        if resp.status in (401, 402, 403, 429):
            raise AuthRequired() if resp.status in (401, 402) else RestrictedContent(
                "The site blocked automated access to this page.")
        if resp.status == 404 or resp.status == 410:
            raise MediaNotFound()
        if resp.status != 200:
            raise UpstreamError()
        page = parse_page(resp.text, resp.url)
        if page["login_wall"] and not (page["images"] or page["videos"]):
            raise AuthRequired()
        formats: list[MediaFormat] = []
        for i, u in enumerate(dict.fromkeys(page["videos"])):
            formats.append(MediaFormat(id=f"preview-video-{i}", kind=MediaKind.VIDEO, ext="mp4",
                                       label="Preview video", url=u, is_preview=True, has_audio=True))
        for i, u in enumerate(dict.fromkeys(page["images"])):
            m = _EXT_RE.search(u)
            formats.append(MediaFormat(id=f"preview-image-{i}", kind=MediaKind.IMAGE,
                                       ext=(m.group(1).lower().replace("jpeg", "jpg") if m else "jpg"),
                                       label="Preview image", url=u, is_preview=True))
        if not formats:
            raise UnsupportedURL("No publicly accessible media was found on this page.")
        thumb = page["images"][0] if page["images"] else None
        mtype = MediaKind.VIDEO if page["videos"] else MediaKind.IMAGE
        item = MediaItem(id="1", media_type=mtype, title=page["title"], thumbnail=thumb, formats=formats)
        return MediaInfo(platform=self.platform, url=url, title=page["title"], thumbnail=thumb,
                         items=[item], notes=[self.preview_note])

    async def download(self, url: str, item: MediaItem, fmt: MediaFormat,
                       dest_dir: Path, ctl: RunControl) -> Path:
        if not fmt.url:
            raise InvalidRequest("This format cannot be downloaded directly.")
        tmp = dest_dir / "download.tmp"
        headers = await self.ctx.fetcher.download_to(
            fmt.url, tmp, self.ctx.settings.max_file_bytes, deadline=ctl.deadline,
            progress=lambda d, t: ctl.report("downloading", d, t), check=ctl.check, accept="image/*,video/*")
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        ext = EXT_BY_TYPE.get(ctype)
        if ext is None:
            tmp.unlink(missing_ok=True)
            raise InvalidMedia("The source did not return a supported image or video file.")
        final = dest_dir / f"media.{ext}"
        tmp.replace(final)
        return final
