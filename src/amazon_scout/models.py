from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MetricKind(str, Enum):
    OBSERVED = "observed"
    CALCULATED = "calculated"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class Provenance:
    source: str
    collected_at: str
    marketplace_id: str = "A2VIGQ35RCS4UG"
    kind: MetricKind = MetricKind.OBSERVED

    @classmethod
    def now(cls, source: str, kind: MetricKind = MetricKind.OBSERVED) -> "Provenance":
        return cls(source, datetime.now(timezone.utc).isoformat(), kind=kind)


@dataclass(frozen=True)
class Metric:
    value: Any
    provenance: Provenance


@dataclass
class Product:
    asin: str
    title: str
    brand: str | None = None
    product_type: str | None = None
    category: str | None = None
    weight_kg: float | None = None
    dimensions_cm: tuple[float, float, float] | None = None
    variation_count: int | None = None
    price_aed: float | None = None
    sales_rank: int | None = None
    offer_count: int | None = None
    amazon_retail_present: bool | None = None
    source: str = "unknown"
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NicheAnalysis:
    name: str
    products: list[Product]
    catalog_result_count: int | None = None
    brand_analytics_available: bool = False
    query_volume: int | None = None
    fees_aed: float | None = None
    demand_score: float = 0
    demand_confidence: str = "LOW"
    competition_score: float = 0
    risk_score: float = 0
    differentiation_score: float = 50
    margin_potential_score: float = 0
    price_attractiveness_score: float = 0
    opportunity_score: float = 0
    data_confidence_score: float = 0
    risk_reasons: list[str] = field(default_factory=list)

