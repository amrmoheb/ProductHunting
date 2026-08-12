from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class SourceAvailability(str, Enum):
    READY = "READY"
    NOT_CONFIGURED = "NOT CONFIGURED"
    UNSUPPORTED_FOR_UAE = "UNSUPPORTED FOR UAE"


@dataclass(frozen=True)
class SourceStatus:
    name: str
    availability: SourceAvailability
    detail: str = ""


class ResearchSource:
    name = "source"
    paid = False
    required_env: tuple[str, ...] = ()

    def status(self) -> SourceStatus:
        ready = all(os.getenv(key) for key in self.required_env)
        return SourceStatus(self.name, SourceAvailability.READY if ready else SourceAvailability.NOT_CONFIGURED)


@dataclass
class PaidProviderBudget:
    allow: bool = False
    max_calls: int = 0
    max_cost_usd: float = 0
    calls_used: int = 0
    cost_used_usd: float = 0
    calls_attempted: int = 0
    calls_succeeded: int = 0
    calls_failed: int = 0
    calls_saved_by_cache: int = 0

    @classmethod
    def from_environment(cls) -> "PaidProviderBudget":
        return cls(
            allow=os.getenv("RESEARCH_ALLOW_PAID_PROVIDERS", "false").lower() == "true",
            max_calls=max(0, int(os.getenv("RESEARCH_MAX_PAID_CALLS", "0"))),
            max_cost_usd=max(0.0, float(os.getenv("RESEARCH_MAX_COST_USD", "0"))),
        )

    def authorize(self, estimated_cost_usd: float = 0) -> None:
        if not self.allow:
            raise PermissionError("Paid providers are disabled")
        if self.calls_used + 1 > self.max_calls:
            raise PermissionError("Paid provider call limit would be exceeded")
        if self.cost_used_usd + estimated_cost_usd > self.max_cost_usd:
            raise PermissionError("Paid provider cost limit would be exceeded")
        self.calls_used += 1
        self.calls_attempted += 1
        self.cost_used_usd += estimated_cost_usd

    @property
    def calls_remaining(self) -> int:
        return max(0, self.max_calls - self.calls_attempted)

    def succeeded(self) -> None:
        self.calls_succeeded += 1

    def failed(self) -> None:
        self.calls_failed += 1
