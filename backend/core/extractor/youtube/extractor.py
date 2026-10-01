from core.extractor.common.ytdlp_extractor import YtDlpExtractor


class YouTubeExtractor(YtDlpExtractor):
    """Public YouTube videos via yt-dlp. Age-gated, members-only, private and
    DRM-protected videos are reported as errors, never bypassed."""

    platform = "YouTube"
    hosts = ("youtube.com", "youtu.be", "youtube-nocookie.com")
    allowed = ("youtube",)
