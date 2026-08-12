from .base import ResearchSource, SourceAvailability, SourceStatus


class CodexWebSource(ResearchSource):
    name = "Codex live web search"

    def status(self) -> SourceStatus:
        return SourceStatus(self.name, SourceAvailability.READY, "Codex orchestrates browsing; Python only ingests evidence")

    def fetch(self, *args, **kwargs):
        raise RuntimeError("Python must never call Codex web search; create an evidence bundle through Codex")
