from __future__ import annotations

from core.errors import UnsupportedURL
from core.extractor.base.extractor import Extractor, ExtractorContext
from core.security.url_guard import ParsedURL, host_matches


class ExtractorRegistry:
    def __init__(self, ctx: ExtractorContext):
        self.ctx = ctx
        self._extractors: list[Extractor] = []

    def register(self, cls: type[Extractor]) -> None:
        self._extractors.append(cls(self.ctx))

    def detect(self, parsed: ParsedURL) -> Extractor:
        for ex in self._extractors:
            if host_matches(parsed.host, ex.hosts):
                return ex
        raise UnsupportedURL(
            "This site is not supported. Supported: "
            + ", ".join(e.platform for e in self._extractors) + "."
        )

    @property
    def platforms(self) -> list[str]:
        return [e.platform for e in self._extractors]
