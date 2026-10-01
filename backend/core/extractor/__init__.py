from core.extractor.base import Extractor, ExtractorContext, ExtractorRegistry
from core.extractor.freepik import FreepikExtractor
from core.extractor.instagram import InstagramExtractor
from core.extractor.shutterstock import ShutterstockExtractor
from core.extractor.youtube import YouTubeExtractor

DEFAULT_EXTRACTORS = (YouTubeExtractor, InstagramExtractor, FreepikExtractor, ShutterstockExtractor)


def build_registry(ctx: ExtractorContext) -> ExtractorRegistry:
    reg = ExtractorRegistry(ctx)
    for cls in DEFAULT_EXTRACTORS:
        reg.register(cls)
    return reg


__all__ = ["Extractor", "ExtractorContext", "ExtractorRegistry", "build_registry", "DEFAULT_EXTRACTORS"]
