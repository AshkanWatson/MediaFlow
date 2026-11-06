from core.extractor.common.ytdlp_extractor import YtDlpExtractor


class InstagramExtractor(YtDlpExtractor):
    """Public Instagram posts/reels via yt-dlp's Instagram extractor.

    Instagram increasingly serves a login wall even for public content, and
    stories always require login. Those cases surface as AUTH_REQUIRED; no
    credentials/cookies are used and nothing is bypassed.
    """

    platform = "Instagram"
    hosts = ("instagram.com", "instagr.am")
    allowed = ("instagram",)
