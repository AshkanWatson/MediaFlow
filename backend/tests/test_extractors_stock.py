import pytest

from core.downloader import resolve_selection
from core.errors import AuthRequired, InvalidMedia, PreviewOnly, RestrictedContent, UnsupportedURL
from core.extractor.common.opengraph import parse_page
from core.extractor.freepik import FreepikExtractor
from core.extractor.shutterstock import ShutterstockExtractor
from core.jobs.control import RunControl
from core.models import DownloadRequest, MediaKind
from tests.fakes import FakeFetcher, ctx

PAGE = """<html><head><title>Fallback</title>
<meta property="og:title" content="Sunset over sea">
<meta property="og:image" content="https://img.example-cdn.com/preview/1.jpg?w=500">
<meta property="og:description" content="A sunset">
<script type="application/ld+json">{"@type":"ImageObject","contentUrl":"https://img.example-cdn.com/big.png"}</script>
</head><body></body></html>"""

URL = "https://www.freepik.com/free-photo/sunset_1.htm"


async def analyze(settings, page=PAGE, status=200, cls=FreepikExtractor, url=URL, files=None):
    fetcher = FakeFetcher(pages={url: (status, page)}, files=files or {})
    ex = cls(ctx(settings, fetcher))
    return ex, fetcher, await ex.analyze(url)


async def test_freepik_preview_metadata(settings):
    _, _, info = await analyze(settings)
    assert info.platform == "Freepik" and info.title == "Sunset over sea"
    fmts = info.items[0].formats
    assert [f.url for f in fmts][0].endswith("big.png")  # JSON-LD contentUrl first
    assert all(f.is_preview for f in fmts) and "licen" in info.notes[0].lower()
    assert all(f.url is None for f in [type(f).model_validate(f.model_dump(mode="json")) for f in fmts])  # url hidden


async def test_preview_requires_explicit_acceptance(settings):
    _, _, info = await analyze(settings)
    with pytest.raises(PreviewOnly):
        resolve_selection(info, DownloadRequest(url="u"))
    item, fmt = resolve_selection(info, DownloadRequest(url="u", accept_preview=True))
    assert fmt.kind == MediaKind.IMAGE


async def test_shutterstock_download_and_extension_from_content_type(settings, tmp_path):
    url = "https://www.shutterstock.com/image-photo/x-1"
    ex, fetcher, info = await analyze(settings, url=url, cls=ShutterstockExtractor,
                                      files={"https://img.example-cdn.com/big.png": ("image/png", b"PNGDATA")})
    assert "watermark" in info.notes[0].lower()
    item, fmt = resolve_selection(info, DownloadRequest(url=url, accept_preview=True))
    path = await ex.download(url, item, fmt, tmp_path, RunControl(30))
    assert path.name == "media.png" and path.read_bytes() == b"PNGDATA"
    assert not (tmp_path / "download.tmp").exists()


async def test_download_rejects_unexpected_content_type(settings, tmp_path):
    url = "https://www.shutterstock.com/image-photo/x-1"
    ex, _, info = await analyze(settings, url=url, cls=ShutterstockExtractor,
                                files={"https://img.example-cdn.com/big.png": ("text/html", b"<script>")})
    item, fmt = resolve_selection(info, DownloadRequest(url=url, accept_preview=True))
    with pytest.raises(InvalidMedia):
        await ex.download(url, item, fmt, tmp_path, RunControl(30))
    assert list(tmp_path.iterdir()) == []


async def test_video_preview(settings):
    page = '<meta property="og:title" content="Clip"><meta property="og:video" content="https://v.cdn.com/p.mp4">'
    _, _, info = await analyze(settings, page=page)
    assert info.items[0].media_type == MediaKind.VIDEO


async def test_http_status_mapping(settings):
    with pytest.raises(AuthRequired):
        await analyze(settings, status=401)
    with pytest.raises(RestrictedContent):
        await analyze(settings, status=403)


async def test_login_wall_and_empty_pages(settings):
    with pytest.raises(AuthRequired):
        await analyze(settings, page="<title>Please sign in</title>")
    with pytest.raises(UnsupportedURL):
        await analyze(settings, page="<title>Hello</title>")


def test_non_https_and_relative_assets():
    p = parse_page('<meta property="og:image" content="http://insecure/x.jpg">'
                   '<meta property="og:video" content="/v.mp4">', "https://www.freepik.com/a/b")
    assert p["images"] == [] and p["videos"] == ["https://www.freepik.com/v.mp4"]


def test_malformed_jsonld_ignored():
    p = parse_page('<script type="application/ld+json">{not json</script><meta property="og:image" content="https://a/b.jpg">',
                   "https://x.com/")
    assert p["images"] == ["https://a/b.jpg"]
