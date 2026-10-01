from core.extractor.common.opengraph import OpenGraphExtractor


class FreepikExtractor(OpenGraphExtractor):
    platform = "Freepik"
    hosts = ("freepik.com",)
    preview_note = (
        "Freepik only exposes a reduced-size preview publicly. Original files require a "
        "Freepik account/licence; MediaFlow does not bypass this or modify attribution/watermarks."
    )
