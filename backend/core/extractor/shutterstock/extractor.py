from core.extractor.common.opengraph import OpenGraphExtractor


class ShutterstockExtractor(OpenGraphExtractor):
    platform = "Shutterstock"
    hosts = ("shutterstock.com",)
    preview_note = (
        "Shutterstock previews are watermarked and low resolution. Licensed originals require a "
        "purchase/subscription; MediaFlow does not remove watermarks or bypass licensing."
    )
