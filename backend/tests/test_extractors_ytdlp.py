import pytest

from core.errors import (AuthRequired, InvalidRequest, MediaNotFound, RestrictedContent, UnsupportedURL,
                         UpstreamError)
from core.extractor import build_registry
from core.extractor.common.ytdlp import map_ytdlp_error
from core.extractor.instagram import InstagramExtractor
from core.extractor.youtube import YouTubeExtractor
from core.jobs.control import RunControl
from core.models import DownloadRequest, MediaKind
from core.downloader import resolve_selection
from core.security import parse_url
from tests.fakes import FakeYtDlp, IG_CAROUSEL, YT_INFO, ctx
from yt_dlp.utils import DownloadError, UnsupportedError


def yt(settings, info=YT_INFO):
    ex = YouTubeExtractor(ctx(settings), client=FakeYtDlp(info))
    return ex, ex.client


async def test_youtube_formats_listing(settings):
    ex, client = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    item = info.items[0]
    assert info.platform == "YouTube" and info.duration == 61 and item.media_type == MediaKind.VIDEO
    video = [f for f in item.formats if f.kind == MediaKind.VIDEO]
    assert [f.height for f in video] == [2160, 1080, 720, 360]  # one per resolution, best first
    assert next(f for f in video if f.height == 1080).id == "137"  # mp4/h264 preferred over webm
    assert next(f for f in video if f.height == 360).has_audio
    audio = [f for f in item.formats if f.kind == MediaKind.AUDIO]
    assert {f.ext for f in audio} == {"m4a", "webm"} and audio[0].id == "251"  # highest abr first
    assert all(f.id != "sb0" for f in item.formats)  # storyboards dropped
    assert client.calls[0][2] == ("youtube",)
    assert "url" not in info.model_dump(mode="json")["items"][0]["formats"][0]


async def test_youtube_download_merges_video_and_audio(settings, tmp_path):
    ex, client = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    item, fmt = resolve_selection(info, DownloadRequest(url="u", format_id="137"))
    path = await ex.download("https://youtu.be/abc123", item, fmt, tmp_path, RunControl(30))
    kind, selector, merge, idx, allowed = client.calls[-1]
    assert selector == "137+140" and merge == "mp4" and idx is None and allowed == ("youtube",)
    assert path.parent == tmp_path


async def test_youtube_webm_video_merges_to_mkv(settings, tmp_path):
    ex, client = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    item, fmt = resolve_selection(info, DownloadRequest(url="u", format_id="313"))
    await ex.download("https://youtu.be/abc123", item, fmt, tmp_path, RunControl(30))
    assert client.calls[-1][1].startswith("313+") and client.calls[-1][2] == "mkv"


async def test_youtube_progressive_format_downloads_alone(settings, tmp_path):
    ex, client = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    item, fmt = resolve_selection(info, DownloadRequest(url="u", format_id="18"))
    await ex.download("https://youtu.be/abc123", item, fmt, tmp_path, RunControl(30))
    assert client.calls[-1][1] == "18"


async def test_audio_only_never_selects_video_stream(settings):
    ex, _ = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    _, fmt = resolve_selection(info, DownloadRequest(url="u", output="mp3"))
    assert fmt.kind == MediaKind.AUDIO
    _, fmt = resolve_selection(info, DownloadRequest(url="u", output="m4a", format_id="137"))
    assert fmt.kind == MediaKind.AUDIO


async def test_selection_rejects_unknown_ids(settings):
    ex, _ = yt(settings)
    info = await ex.analyze("https://youtu.be/abc123")
    for bad in ("137; rm -rf /", "999", "best"):
        with pytest.raises(InvalidRequest):
            resolve_selection(info, DownloadRequest(url="u", format_id=bad))
    with pytest.raises(InvalidRequest):
        resolve_selection(info, DownloadRequest(url="u", item_id="nope"))


async def test_no_formats_is_not_found(settings):
    ex, _ = yt(settings, {"id": "x", "title": "t", "formats": []})
    with pytest.raises(MediaNotFound):
        await ex.analyze("https://youtu.be/x")


async def test_instagram_carousel_items(settings, tmp_path):
    ex = InstagramExtractor(ctx(settings), client=FakeYtDlp(IG_CAROUSEL))
    info = await ex.analyze("https://www.instagram.com/p/post1/")
    assert [i.media_type for i in info.items] == [MediaKind.VIDEO, MediaKind.IMAGE]
    assert [i.index for i in info.items] == [1, 2]
    item, fmt = resolve_selection(info, DownloadRequest(url="u", item_id="e2"))
    await ex.download("https://www.instagram.com/p/post1/", item, fmt, tmp_path, RunControl(30))
    assert ex.client.calls[-1][3] == 2 and ex.client.calls[-1][4] == ("instagram",)


def test_registry_detects_platforms(settings):
    reg = build_registry(ctx(settings))
    cases = {"https://www.youtube.com/watch?v=1": "YouTube", "https://m.youtube.com/watch?v=1": "YouTube",
             "https://youtu.be/1": "YouTube", "https://www.instagram.com/reel/x/": "Instagram",
             "https://www.freepik.com/free-photo/x": "Freepik", "https://www.shutterstock.com/image-photo/x": "Shutterstock"}
    for url, name in cases.items():
        assert reg.detect(parse_url(url)).platform == name
    for url in ("https://evil.com/youtube.com", "https://youtube.com.evil.com/", "http://93.184.216.34/",
                "https://notyoutube.com/", "https://example.com/"):
        with pytest.raises(UnsupportedURL):
            reg.detect(parse_url(url))


@pytest.mark.parametrize("msg,exc", [
    ("Sign in to confirm you're not a bot", AuthRequired),
    ("Private video. Sign in if you've been granted access", AuthRequired),
    ("login required to view this", AuthRequired),
    ("Video unavailable. This video has been removed", MediaNotFound),
    ("This video is not available in your country", RestrictedContent),
    ("DRM protected", RestrictedContent),
    ("No suitable extractor found for URL https://example.com/", UnsupportedURL),
    ("Unable to download API page: ('Unable to connect to proxy'); Confirm you are on the latest version", UpstreamError),
])
def test_error_mapping(msg, exc):
    assert isinstance(map_ytdlp_error(DownloadError(msg)), exc)


def test_error_mapping_unsupported():
    assert isinstance(map_ytdlp_error(UnsupportedError("http://x")), UnsupportedURL)
