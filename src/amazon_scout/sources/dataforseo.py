from .base import ResearchSource, SourceAvailability, SourceStatus


class DataForSEOSource(ResearchSource):
    name = "DataForSEO"
    paid = True
    required_env = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD")

    def status(self) -> SourceStatus:
        base = super().status()
        if base.availability != SourceAvailability.READY:
            return base
        return SourceStatus(self.name, SourceAvailability.UNSUPPORTED_FOR_UAE, "Amazon Labs is currently US/English-only; discover Merchant API UAE support before use")

    def amazon_labs_request(self, *args, **kwargs):
        raise RuntimeError("DataForSEO Amazon Labs cannot be used for UAE; US data substitution is forbidden")
