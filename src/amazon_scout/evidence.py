from __future__ import annotations

import json
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

UAE_MARKETPLACES = {"amazon.ae", "A2VIGQ35RCS4UG"}


class EvidenceStrength(str, Enum):
    VERY_HIGH = "VERY_HIGH"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class EvidenceFreshness(str, Enum):
    CURRENT = "CURRENT"
    STATIC_GUIDANCE = "STATIC_GUIDANCE"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class MarketRelevance(str, Enum):
    AMAZON_UAE = "AMAZON_UAE"
    UAE_RETAIL = "UAE_RETAIL"
    UAE_GENERAL = "UAE_GENERAL"
    GCC = "GCC"
    GLOBAL = "GLOBAL"
    OTHER_MARKETPLACE = "OTHER_MARKETPLACE"
    UNKNOWN = "UNKNOWN"


def parse_aware_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    research_run_id: str
    metric_name: str
    metric_value: str | int | float | bool | None
    metric_unit: str | None
    asin: str | None
    keyword: str | None
    niche: str | None
    marketplace: str
    source_provider: str
    source_type: str
    source_url: str | None
    source_title: str | None
    observed_at: str
    retrieved_at: str
    confidence: EvidenceStrength
    is_estimate: bool
    notes: str | None = None
    market_relevance: MarketRelevance = MarketRelevance.UNKNOWN
    source_timezone: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any], run_id: str, *, validation_time: datetime | None = None, clock_skew_minutes: int = 5) -> "EvidenceRecord":
        marketplace = raw.get("marketplace")
        if marketplace not in UAE_MARKETPLACES:
            raise ValueError(f"Non-UAE marketplace rejected: {marketplace!r}")
        value = raw.get("metric_value")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Numeric evidence must be finite")
        if isinstance(value, (dict, list)):
            raise ValueError("metric_value must be a scalar or null")
        observed = parse_aware_datetime(raw["observed_at"], "observed_at")
        retrieved = parse_aware_datetime(raw["retrieved_at"], "retrieved_at")
        limit = (validation_time or datetime.now(timezone.utc)) + timedelta(minutes=clock_skew_minutes)
        if observed > limit:
            raise ValueError(f"Evidence {raw.get('id', '<unknown>')} observed_at is in the future")
        if retrieved > limit:
            raise ValueError(f"Evidence {raw.get('id', '<unknown>')} retrieved_at is in the future")
        url = raw.get("source_url")
        if url and urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("source_url must use http or https")
        relevance_raw = raw.get("market_relevance", "UNKNOWN")
        return cls(
            id=str(raw.get("id") or uuid.uuid4()), research_run_id=run_id,
            metric_name=str(raw["metric_name"]), metric_value=value,
            metric_unit=raw.get("metric_unit"), asin=raw.get("asin"), keyword=raw.get("keyword"),
            niche=raw.get("niche"), marketplace=marketplace,
            source_provider=str(raw["source_provider"]), source_type=str(raw["source_type"]),
            source_url=url, source_title=raw.get("source_title"), observed_at=utc_iso(observed),
            retrieved_at=utc_iso(retrieved), confidence=EvidenceStrength(raw["confidence"]),
            is_estimate=bool(raw["is_estimate"]), notes=raw.get("notes"),
            market_relevance=MarketRelevance(relevance_raw), source_timezone=raw.get("source_timezone"),
        )

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["confidence"] = self.confidence.value
        result["market_relevance"] = self.market_relevance.value
        return result


def load_freshness_config(path: str | Path = "config/evidence_freshness.yaml") -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def freshness_for(record: EvidenceRecord, as_of: datetime, config: dict[str, Any] | None = None) -> EvidenceFreshness:
    config = config or load_freshness_config()
    metric = record.metric_name
    if metric in {"regulatory_risk", "risk_score"} and record.source_type == "official_government_web":
        return EvidenceFreshness.STATIC_GUIDANCE
    if metric in {"current_price_aed", "observed_market_price_aed"}: group = "retail_price"
    elif metric in {"bestseller_rank", "search_position", "bestseller_badge"}: group = "amazon_rank"
    elif "fee" in metric: group = "official_fee"
    elif metric in {"regulatory_risk", "risk_score"}: group = "regulatory"
    elif "amazon" in record.source_type or "indexed" in record.source_type: group = "amazon_indexed"
    else: group = "default"
    observed = parse_aware_datetime(record.observed_at, "observed_at")
    age = (as_of.astimezone(timezone.utc) - observed).total_seconds() / 86400
    if age < 0: return EvidenceFreshness.UNKNOWN
    window = config["windows_days"][group]
    if age <= window["current"]: return EvidenceFreshness.CURRENT
    if age <= window["aging"]: return EvidenceFreshness.AGING
    return EvidenceFreshness.STALE


def _validate_funnel_input(funnel: dict[str, Any]) -> None:
    for value in funnel.values():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("candidate_funnel values must be non-negative integers")


def validate_bundle(raw: dict[str, Any], *, validation_time: datetime | None = None, quarantine_future: bool = False) -> tuple[dict[str, Any], list[EvidenceRecord]]:
    for key in ("research_run", "keywords", "products", "evidence", "source_summary"):
        if key not in raw: raise ValueError(f"Missing bundle field: {key}")
    run = raw["research_run"]
    if run.get("marketplace") not in UAE_MARKETPLACES: raise ValueError("Research run must target amazon.ae/A2VIGQ35RCS4UG")
    run_id = str(run.get("id") or uuid.uuid4()); run["id"] = run_id
    check_time = (validation_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    run_errors: list[dict[str, Any]] = []
    for field in ("started_at", "evidence_cutoff"):
        parsed = parse_aware_datetime(run[field], f"research_run.{field}")
        if parsed > check_time + timedelta(minutes=5):
            message = f"research_run.{field} is in the future beyond the 5-minute clock-skew allowance"
            if quarantine_future:
                run_errors.append({"field": field, "reason": message})
            else:
                raise ValueError(message)
    raw["_validation_errors"] = run_errors
    _validate_funnel_input(run.get("candidate_funnel", {}))
    if not isinstance(raw["evidence"], list) or not raw["evidence"]: raise ValueError("At least one evidence record is required")
    records: list[EvidenceRecord] = []; quarantined: list[dict[str, Any]] = []
    for item in raw["evidence"]:
        try:
            records.append(EvidenceRecord.from_dict(item, run_id, validation_time=validation_time))
        except ValueError as exc:
            if quarantine_future and "in the future" in str(exc):
                quarantined.append({"id": item.get("id"), "reason": str(exc)})
            else: raise
    raw["_quarantined_evidence"] = quarantined
    seen: set[str] = set()
    for record in records:
        if record.id in seen: raise ValueError(f"Duplicate evidence id in bundle: {record.id}")
        seen.add(record.id)
    for product in raw["products"]:
        if product.get("marketplace", "amazon.ae") not in UAE_MARKETPLACES: raise ValueError("Non-UAE product data rejected")
        for field in ("current_price_aed", "observed_market_price_aed", "proposed_selling_price_aed", "bundle_hypothesis_price_aed", "fee_calculation_price_aed", "original_price_aed", "rating", "review_count", "search_position", "weight_kg", "variation_count"):
            value = product.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0): raise ValueError(f"Invalid numeric product field {field}: {value!r}")
    return raw, records


def load_bundle(path: str | Path, **kwargs: Any) -> tuple[dict[str, Any], list[EvidenceRecord]]:
    with Path(path).open(encoding="utf-8") as handle:
        return validate_bundle(json.load(handle), **kwargs)
