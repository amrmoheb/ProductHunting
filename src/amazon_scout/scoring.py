from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .normalization import clamp


def load_scoring_config(path: str | Path = "config/scoring.yaml") -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def opportunity_score(factors: dict[str, float | None], weights: dict[str, float]) -> float:
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("Scoring weights must sum to 1.0")
    missing = set(weights) - set(factors)
    if missing:
        raise ValueError(f"Missing scoring factors: {sorted(missing)}")
    # Missing evidence is conservative, not silently imputed as attractive.
    return round(sum(weights[key] * clamp(float(factors[key] or 0)) for key in weights), 2)


def opportunity_score_breakdown(factors: dict[str, float | None], weights: dict[str, float], *, confidence: float | None = None) -> dict[str, Any]:
    """Expose the exact current formula without changing its behavior."""
    score = opportunity_score(factors, weights)
    components: dict[str, dict[str, Any]] = {}
    for name, weight in weights.items():
        raw = factors[name]
        effective = clamp(float(raw)) if raw is not None else 0.0
        components[name] = {
            "raw": raw,
            "weight": float(weight),
            "effective_raw": effective,
            "contribution": round(float(weight) * effective, 4),
            "missing_evidence_behavior": "TREATED_AS_ZERO" if raw is None else "OBSERVED_OR_CALCULATED",
        }
    return {
        "components": components,
        "penalties": [],
        "confidence_adjustment": {"applied": False, "multiplier": 1.0, "confidence": confidence, "behavior": "SEPARATE_GATE_ONLY"},
        "final_pre_confidence_score": score,
        "final_validated_opportunity_score": score,
        "arithmetic_sum": round(sum(item["contribution"] for item in components.values()), 2),
    }


def synthetic_ceiling_audit(weights: dict[str, float]) -> dict[str, Any]:
    perfect={name:100.0 for name in weights}
    very_good={"demand":85.0,"competition_attractiveness":75.0,"margin_potential":85.0,"price_attractiveness":90.0,"risk_attractiveness":90.0,"differentiation_potential":80.0}
    return {
        "PERFECT_CANDIDATE": opportunity_score_breakdown(perfect,weights,confidence=100.0),
        "VERY_GOOD_CANDIDATE": opportunity_score_breakdown(very_good,weights,confidence=85.0),
    }


def score_label(score: float, bands: list[list[Any]]) -> str:
    for threshold, label in bands:
        if score >= threshold:
            return str(label)
    return "Unrated"


def data_confidence(*, brand_analytics: bool, pricing: bool, sales_rank: bool, sample_size: int, fee_estimate: bool, newest_observation: str | None, config: dict[str, Any]) -> float:
    cfg = config["confidence"]
    score = 0.0
    score += cfg["brand_analytics"] if brand_analytics else 0
    score += cfg["pricing"] if pricing else 0
    score += cfg["sales_rank"] if sales_rank else 0
    score += cfg["sample_size"] * min(1, sample_size / cfg["adequate_sample_size"])
    score += cfg["fee_estimate"] if fee_estimate else 0
    if newest_observation:
        try:
            observed = datetime.fromisoformat(newest_observation.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).days
            score += cfg["recent"] if age <= cfg["recent_days"] else max(0, cfg["recent"] * (1 - age / 90))
        except ValueError:
            pass
    return round(clamp(score), 2)
