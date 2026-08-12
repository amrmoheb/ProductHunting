from .base import ResearchSource, SourceAvailability, SourceStatus


class AmazonPublicSource(ResearchSource):
    name = "Amazon UAE official pages"

    def status(self) -> SourceStatus:
        return SourceStatus(self.name, SourceAvailability.READY, "Public sell.amazon.ae sources; refreshed by Codex web research")
