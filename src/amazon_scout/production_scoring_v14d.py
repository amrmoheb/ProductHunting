from __future__ import annotations

from typing import Any

from .scoring_calibration_v14c import COMPETITION_WEIGHTS, DEMAND_WEIGHTS, PROPOSED_OPPORTUNITY_WEIGHTS, _opportunity, calibrate_candidate

SCORING_VERSION = "V1.4D"
STRONG_SCORE_THRESHOLD = 65.0
VALIDATED_CONFIDENCE_MINIMUM = 55.0
STRONG_CONFIDENCE_MINIMUM = 70.0
DATAFORSEO_ROLES = {
    "bulk_search_volume_ar": "SUPPLEMENTAL_ONLY_PARTIAL_UAE_DEMAND_CAPPED_AT_10_PERCENT_OF_SEARCH_FAMILY",
    "amazon_labs_en": "NOT_CONFIRMED",
    "product_competitors": "COMPETITION_INTELLIGENCE_WHEN_OBSERVED",
    "ranked_keywords": "SUPPLEMENTAL_COMPETITION_WHEN_OBSERVED",
}


def _dataforseo_input(analysis: dict[str, Any]) -> dict[str, Any]:
    """Adapt persisted optional evidence; never collect provider data while scoring."""
    value = analysis.get("dataforseo_competition_evidence") or {}
    return {"candidate": analysis["niche"], "representative_asin": value.get("representative_asin"), "product_competitors": value.get("product_competitors") or [], "ranked_keywords": value.get("ranked_keywords") or [], "endpoint_outcomes": value.get("endpoint_outcomes") or {}}


def eligibility_tier(score: float | None, confidence: float, risk_status: str, economics_status: str, economics_confidence: float, *, gates_pass: bool) -> dict[str, str]:
    if not gates_pass or score is None:
        return {"maximum_tier": "PRELIMINARY_NEEDS_EVIDENCE", "reason": "Required production evidence gates did not pass."}
    if confidence < VALIDATED_CONFIDENCE_MINIMUM:
        return {"maximum_tier": "PRELIMINARY_NEEDS_EVIDENCE", "reason": "Confidence is below 55."}
    if confidence < STRONG_CONFIDENCE_MINIMUM or score < STRONG_SCORE_THRESHOLD:
        return {"maximum_tier": "VALIDATED", "reason": "Confidence 55-69 or score below the strong threshold caps the tier at VALIDATED."}
    if risk_status in {"UNKNOWN", "INSUFFICIENT"}:
        return {"maximum_tier": "VALIDATED", "reason": "UNKNOWN risk cannot become STRONG."}
    if economics_status in {"UNKNOWN", "INSUFFICIENT"}:
        return {"maximum_tier": "VALIDATED", "reason": "Economics support is inadequate for STRONG."}
    if economics_status == "PARTIAL" and economics_confidence < VALIDATED_CONFIDENCE_MINIMUM:
        return {"maximum_tier": "VALIDATED", "reason": "Low-confidence PARTIAL economics cannot create STRONG."}
    return {"maximum_tier": "STRONG_ELIGIBLE", "reason": "Score, confidence, risk, economics, and evidence gates support STRONG eligibility."}


def score_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    """Apply the frozen V1.4C model as canonical V1.4D production scoring."""
    scored = calibrate_candidate(analysis, analysis.get("dataforseo_arabic_search_evidence") or {"normalized_keyword_rows": []}, _dataforseo_input(analysis))
    proposed = scored["proposed"]
    if analysis["components"]["demand"].get("score") is None:
        proposed["demand_score"] = None; proposed["demand_confidence"] = 0.0
    if analysis["components"]["competition"].get("score") is None:
        proposed["competition_score"] = None; proposed["competition_confidence"] = 0.0
    economics = analysis.get("economics") or {}
    economics_raw = (economics.get("score") or {}).get("raw") if isinstance(economics.get("score"), dict) else economics.get("score")
    proposed["opportunity_arithmetic"] = _opportunity(proposed["demand_score"], proposed["competition_score"], economics_raw, analysis.get("risk_score"), {"demand": proposed["demand_confidence"], "competition": proposed["competition_confidence"], "economics": economics.get("confidence", 0), "risk": analysis.get("risk_confidence", 0)})
    proposed["opportunity_score"] = proposed["opportunity_arithmetic"]["score"]
    proposed["overall_evidence_confidence"] = proposed["opportunity_arithmetic"]["confidence"]
    required_gates = all((analysis.get("gates") or {}).get(name, {}).get("gate") is True for name in ("price", "demand", "competition", "risk"))
    tier = eligibility_tier(proposed["opportunity_score"], proposed["overall_evidence_confidence"], analysis.get("risk_status", "UNKNOWN"), economics.get("status", "UNKNOWN"), economics.get("confidence", 0) or 0, gates_pass=required_gates)
    if analysis.get("candidate_type") == "BUNDLE_HYPOTHESIS": tier = {"maximum_tier": "BUNDLE_HYPOTHESIS", "reason": "Hypothetical bundle pricing is not sourcing validation."}
    elif analysis.get("commercial_opportunity_classification") == "PREMIUM_POSITIONING_HYPOTHESIS": tier = {"maximum_tier": "PREMIUM_POSITIONING_HYPOTHESIS", "reason": "Premium willingness-to-pay remains hypothetical."}
    elif analysis.get("recommendation_tier") == "REJECTED_CONSTRAINT": tier = {"maximum_tier": "REJECTED_CONSTRAINT", "reason": "The candidate failed an explicit user price constraint."}
    elif analysis.get("recommendation_tier") == "HIGH_RISK": tier = {"maximum_tier": "HIGH_RISK", "reason": "Risk threshold blocks recommendation."}
    breakdown_components = {row["component"]: {"raw": row["score"], "weight": row["weight"], "contribution": row["contribution"], "missing_evidence_behavior": row["missing_behavior"]} for row in proposed["opportunity_arithmetic"]["arithmetic"]}
    result = dict(analysis)
    result["legacy_score_breakdown"] = analysis.get("score_breakdown")
    result.update({
        "scoring_version": SCORING_VERSION, "production_scoring_model": SCORING_VERSION,
        "demand_score": proposed["demand_score"], "demand_confidence": proposed["demand_confidence"], "demand_status": analysis["components"]["demand"]["status"] if proposed["demand_score"] is None else proposed["demand_evidence_status"],
        "competition_score": proposed["competition_score"], "competition_confidence": proposed["competition_confidence"], "competition_status": analysis["components"]["competition"]["status"] if proposed["competition_score"] is None else proposed["competition_evidence_status"],
        "preliminary_opportunity_score": proposed["opportunity_score"], "validated_opportunity_score": proposed["opportunity_score"] if required_gates else None, "opportunity_score": proposed["opportunity_score"],
        "data_confidence_score": proposed["overall_evidence_confidence"], "recommendation_tier": tier["maximum_tier"], "tier_policy_result": tier,
        "technically_validated": required_gates and proposed["overall_evidence_confidence"] >= VALIDATED_CONFIDENCE_MINIMUM,
        "qualified_strong_opportunity": tier["maximum_tier"] == "STRONG_ELIGIBLE", "final_top_10_eligible": tier["maximum_tier"] == "STRONG_ELIGIBLE",
        "top_3_to_source_eligible": tier["maximum_tier"] == "STRONG_ELIGIBLE" and analysis.get("candidate_type") == "OBSERVED_MARKET_OPPORTUNITY",
        "factors": {row["component"]: row["score"] for row in proposed["opportunity_arithmetic"]["arithmetic"]},
        "score_breakdown": {"scoring_version": SCORING_VERSION, "components": breakdown_components, "arithmetic": proposed["opportunity_arithmetic"]["arithmetic"], "fixed_denominator": 1.0, "final_pre_confidence_score": proposed["opportunity_score"], "final_validated_opportunity_score": proposed["opportunity_score"] if required_gates else None, "confidence_adjustment": {"multiplier": 1.0, "behavior": "SEPARATE_GATE_NEVER_MULTIPLIED"}, "penalties": []},
        "v14d_demand": {"families": proposed["demand_evidence_breakdown"], "arithmetic": proposed["demand_arithmetic"]},
        "v14d_competition": {"families": proposed["competition_evidence_breakdown"], "arithmetic": proposed["competition_arithmetic"]},
        "max_landed_cost_25_aed": scored["max_landed_cost_25_aed"], "economics_status": economics.get("status"), "economics_confidence": economics.get("confidence"), "dataforseo_roles": DATAFORSEO_ROLES,
    })
    result["components"] = {**analysis["components"], "demand": {**analysis["components"]["demand"], "score": proposed["demand_score"], "confidence": proposed["demand_confidence"], "status": proposed["demand_evidence_status"]}, "competition": {**analysis["components"]["competition"], "score": proposed["competition_score"], "confidence": proposed["competition_confidence"], "status": proposed["competition_evidence_status"]}}
    result["gates"] = dict(analysis["gates"])
    result["gates"]["confidence"] = {"gate": proposed["overall_evidence_confidence"] >= VALIDATED_CONFIDENCE_MINIMUM, "reason": f"V1.4D confidence {proposed['overall_evidence_confidence']}%; 55 minimum for VALIDATED and 70 for STRONG."}
    return result


__all__ = ["COMPETITION_WEIGHTS", "DATAFORSEO_ROLES", "DEMAND_WEIGHTS", "PROPOSED_OPPORTUNITY_WEIGHTS", "SCORING_VERSION", "eligibility_tier", "score_analysis"]
