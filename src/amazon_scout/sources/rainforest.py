from .base import ResearchSource, SourceAvailability, SourceStatus


class RainforestSource(ResearchSource):
    name = "Rainforest / Traject Data"
    paid = True
    required_env = ("RAINFOREST_API_KEY",)

    def status(self) -> SourceStatus:
        base = super().status()
        if base.availability != SourceAvailability.READY:
            return base
        return SourceStatus(self.name, SourceAvailability.UNSUPPORTED_FOR_UAE, "amazon.ae support was not confirmed in current official documentation; disabled fail-closed")
