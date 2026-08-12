from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urlparse

from .commercial_segments import evaluate_price_gate, load_commercial_config
from .database import ScoutDatabase
from .evidence import EvidenceFreshness, EvidenceRecord, EvidenceStrength, MarketRelevance, freshness_for, load_freshness_config, parse_aware_datetime
from .normalization import clamp, minmax, percentile, price_statistics
from .profitability import maximum_landed_cost, uncertain_fee_scenarios
from .scoring import load_scoring_config, opportunity_score, opportunity_score_breakdown
from .economics_v13 import calculate_candidate_economics
from .sources.provenance import choose_preferred

STRENGTH = {EvidenceStrength.VERY_HIGH: 1.0, EvidenceStrength.HIGH: .85, EvidenceStrength.MEDIUM: .65, EvidenceStrength.LOW: .4, EvidenceStrength.VERY_LOW: .2}
DEMAND_METRICS = {"amazon_search_volume", "search_position", "bestseller_rank", "bestseller_badge", "keyword_visibility", "ranked_keyword_count", "uae_trend_signal", "amazon_visibility", "monthly_purchase_signal_lower_bound", "bought_last_month_raw", "relevant_result_count", "median_reviews"}
COMPETITION_METRICS = {"visible_competing_products", "relevant_result_count", "offer_count", "seller_count", "sponsored_status", "sponsored_density", "search_position", "review_count", "median_reviews", "p75_reviews", "rating", "brand", "brand_concentration", "top_brand_share", "variation_count", "competitor_keyword_overlap", "search_result_density"}
RISK_METRICS = {"regulatory_risk", "risk_score", "fragile", "battery", "hazardous", "weight_kg"}
CANDIDATE_TYPES = {"OBSERVED_MARKET_OPPORTUNITY", "BUNDLE_HYPOTHESIS", "DIFFERENTIATION_HYPOTHESIS"}
STATISTICAL_METRICS = COMPETITION_METRICS | {"current_price_aed", "observed_market_price_aed"}


def _numeric(records: list[EvidenceRecord], name: str) -> list[float]:
    return [float(r.metric_value) for r in records if r.metric_name == name and isinstance(r.metric_value, (int, float)) and not isinstance(r.metric_value, bool)]


def canonical_products_by_asin(products: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep raw rows elsewhere, but return one merged current row per candidate+ASIN."""
    by_asin: dict[str, list[dict[str, Any]]] = defaultdict(list); without_asin=[]
    for product in products:
        asin=str(product.get("asin") or "").strip()
        (by_asin[asin] if asin else without_asin).append(product)
    canonical=[]
    for asin, rows in by_asin.items():
        ordered=sorted(rows,key=lambda row:str(row.get("retrieved_at") or row.get("observed_at") or ""),reverse=True)
        merged=dict(ordered[0])
        for row in ordered[1:]:
            for key,value in row.items():
                if merged.get(key) is None and value is not None: merged[key]=value
        canonical.append(merged)
    canonical.extend(without_asin)
    raw_rows=len(products); unique=len(by_asin)
    return canonical,{"raw_result_rows":raw_rows,"unique_ASINs":unique,"duplicate_ASIN_rows_removed_from_statistics":raw_rows-unique-len(without_asin)}


def canonical_statistical_records(records: list[EvidenceRecord]) -> list[EvidenceRecord]:
    chosen: dict[tuple[str,str],EvidenceRecord]={}; passthrough=[]
    for record in records:
        if not record.asin or record.metric_name not in STATISTICAL_METRICS:
            passthrough.append(record); continue
        key=(record.asin,record.metric_name); current=chosen.get(key)
        if current is None or (record.observed_at,record.retrieved_at,record.id) > (current.observed_at,current.retrieved_at,current.id): chosen[key]=record
    return passthrough+list(chosen.values())


def _effective_relevance(record: EvidenceRecord) -> MarketRelevance:
    if record.market_relevance != MarketRelevance.UNKNOWN:
        return record.market_relevance
    # Backward-compatible classification from explicit URL/source metadata only.
    host = urlparse(record.source_url or "").hostname or ""
    if host == "amazon.ae" or host.endswith(".amazon.ae") or "amazon_uae" in record.source_type or record.source_provider == "sp_api":
        return MarketRelevance.AMAZON_UAE
    if "uae_retail" in record.source_type or record.source_provider.endswith("_uae") or host.endswith("noon.com") or host.endswith("namshi.com"):
        return MarketRelevance.UAE_RETAIL
    if record.source_type in {"official_government_web", "uae_web_search", "uae_supplier_web", "uae_comparison_web"}:
        return MarketRelevance.UAE_GENERAL
    if "global" in (record.notes or "").lower() or "global" in record.source_type:
        return MarketRelevance.GLOBAL
    return MarketRelevance.UNKNOWN


def _fresh(record: EvidenceRecord, as_of: datetime, config: dict[str, Any]) -> EvidenceFreshness:
    return freshness_for(record, as_of, config)


def _component_freshness(records: list[EvidenceRecord], as_of: datetime, config: dict[str, Any]) -> str:
    states = [_fresh(r, as_of, config) for r in records]
    for state in (EvidenceFreshness.CURRENT, EvidenceFreshness.STATIC_GUIDANCE, EvidenceFreshness.AGING, EvidenceFreshness.STALE):
        if state in states: return state.value
    return EvidenceFreshness.UNKNOWN.value


def _candidate_type(product: dict[str, Any]) -> str:
    explicit = product.get("candidate_type")
    if explicit in CANDIDATE_TYPES: return explicit
    if product.get("bundle_hypothesis_price_aed") is not None or "target bundle" in str(product.get("title", "")).lower(): return "BUNDLE_HYPOTHESIS"
    if product.get("proposed_selling_price_aed") is not None: return "DIFFERENTIATION_HYPOTHESIS"
    return "OBSERVED_MARKET_OPPORTUNITY"


def _legacy_fee_basis(records: list[EvidenceRecord]) -> float | None:
    explicit = _numeric(records, "fee_calculation_price_aed")
    if explicit: return explicit[-1]
    for record in records:
        if record.metric_name in {"estimated_referral_fee_aed", "total_estimated_amazon_fees_aed"}:
            match = re.search(r"at\s+AED\s*([0-9]+(?:\.[0-9]+)?)", record.metric_unit or "", re.I)
            if match: return float(match.group(1))
    return None


def _demand_component(records: list[EvidenceRecord], as_of: datetime, fresh_cfg: dict[str, Any]) -> dict[str, Any]:
    all_demand = [r for r in records if r.metric_name in DEMAND_METRICS and r.metric_value is not None]
    current = [r for r in all_demand if _fresh(r, as_of, fresh_cfg) == EvidenceFreshness.CURRENT]
    relevant = [r for r in current if _effective_relevance(r) in {MarketRelevance.AMAZON_UAE, MarketRelevance.UAE_GENERAL}]
    strong = [r for r in relevant if (
        r.source_provider in {"sp_api", "brand_analytics"}
        or (r.metric_name == "amazon_search_volume" and r.confidence in {EvidenceStrength.HIGH, EvidenceStrength.VERY_HIGH})
        or (r.metric_name == "bestseller_rank" and r.confidence in {EvidenceStrength.HIGH, EvidenceStrength.VERY_HIGH} and _effective_relevance(r) == MarketRelevance.AMAZON_UAE)
    )]
    purchase_signals = [r for r in relevant if r.metric_name == "monthly_purchase_signal_lower_bound" and isinstance(r.metric_value, (int,float))]
    if len(purchase_signals) >= 2: strong.extend(purchase_signals)
    weak_dimensions: set[str] = set()
    visible_count = max(_numeric(relevant, "relevant_result_count") or [0])
    if visible_count >= 5 or len({r.asin for r in relevant if r.metric_name == "amazon_visibility" and r.asin}) >= 5: weak_dimensions.add("current_amazon_search_visibility")
    if any(float(r.metric_value) > 0 for r in relevant if r.metric_name == "median_reviews" and isinstance(r.metric_value,(int,float))): weak_dimensions.add("review_depth")
    if any(r.metric_name == "bestseller_badge" for r in relevant): weak_dimensions.add("amazon_badge")
    if len({r.keyword for r in relevant if r.metric_name in {"amazon_visibility","search_position"} and r.keyword}) >= 2: weak_dimensions.add("repeat_keyword_visibility")
    if purchase_signals: weak_dimensions.add("purchase_signal")
    has_amazon_uae = any(_effective_relevance(r) == MarketRelevance.AMAZON_UAE for r in relevant)
    gate = bool(strong) or (len(weak_dimensions) >= 2 and has_amazon_uae)
    if gate: status = "SUFFICIENT"
    elif len(relevant) == 1: status = "WEAK"
    elif all_demand: status = "INSUFFICIENT"
    else: status = "UNKNOWN"
    if not relevant:
        score = None
    else:
        avg = sum(STRENGTH[r.confidence] for r in relevant) / len(relevant)
        score = round(clamp(20 + avg * 55 + min(25, len(relevant) * 6)), 2)
    confidence = round(100 * (sum(STRENGTH[r.confidence] for r in relevant) / max(1, len(relevant))) * (1 if strong else min(1, len(relevant) / 2)), 2) if relevant else 0.0
    if gate: reason = "Meaningful current UAE demand evidence satisfied the deterministic gate."
    elif not all_demand: reason = "Insufficient UAE-specific demand evidence: no meaningful demand observations."
    elif not current: reason = "Insufficient UAE-specific demand evidence: available demand observations are stale or aging."
    elif not has_amazon_uae: reason = "Insufficient UAE-specific demand evidence: no current Amazon UAE signal."
    else: reason = "Insufficient UAE-specific demand evidence: fewer than two distinct weak signal dimensions and no strong signal."
    return {"score": score, "confidence": confidence, "status": status, "gate": gate, "gate_reason": reason, "evidence_ids": [r.id for r in relevant], "observation_count": len(relevant), "weak_dimensions": sorted(weak_dimensions), "purchase_signal_count": len(purchase_signals)}


def _competition_component(records: list[EvidenceRecord], products: list[dict[str, Any]], amazon_prices: list[float], as_of: datetime, fresh_cfg: dict[str, Any]) -> dict[str, Any]:
    all_comp = [r for r in records if r.metric_name in COMPETITION_METRICS and r.metric_value is not None]
    current = [r for r in all_comp if _fresh(r, as_of, fresh_cfg) == EvidenceFreshness.CURRENT and _effective_relevance(r) == MarketRelevance.AMAZON_UAE]
    visible = _numeric(current, "visible_competing_products") + _numeric(current, "relevant_result_count") + _numeric(current, "search_result_density")
    distinct_products = {p.get("asin") or p.get("title") for p in products if p.get("asin") or p.get("title")}
    multiple_products = (max(visible) >= 2 if visible else False) or len(distinct_products) >= 2
    dimensions: dict[str, float] = {}
    if visible: dimensions["product_sample"] = minmax(median(visible), 2, 50, reverse=True)
    elif len(distinct_products) >= 2: dimensions["product_sample"] = minmax(len(distinct_products), 2, 50, reverse=True)
    brands = [str(r.metric_value).strip().lower() for r in current if r.metric_name == "brand" and r.metric_value]
    if len(brands) >= 2:
        counts = Counter(brands); share = max(counts.values()) / len(brands)
        dimensions["brand_concentration"] = round(100 * (1 - share), 2)
    elif _numeric(current,"top_brand_share"):
        dimensions["brand_concentration"] = round(100*(1-median(_numeric(current,"top_brand_share"))),2)
    reviews = _numeric(current, "review_count")
    if len(reviews) >= 2: dimensions["review_distribution"] = minmax(median(reviews), 0, 1000, reverse=True)
    sponsored = [bool(r.metric_value) for r in current if r.metric_name == "sponsored_status"]
    expected_sample = int(max(visible)) if visible else len(distinct_products)
    if len(sponsored) >= 2 and len(sponsored) >= expected_sample: dimensions["sponsored_density"] = round(100 * (1 - sum(sponsored) / len(sponsored)), 2)
    elif _numeric(current,"sponsored_density"): dimensions["sponsored_density"] = round(100*(1-median(_numeric(current,"sponsored_density"))),2)
    if len(amazon_prices) >= 2:
        stats = price_statistics(amazon_prices)
        dimensions["price_dispersion"] = round(100 - min(100, float(stats["dispersion"] or 0) * 100), 2)
    offers = _numeric(current, "offer_count")
    if offers: dimensions["offer_count"] = minmax(median(offers), 1, 20, reverse=True)
    overlap = _numeric(current, "competitor_keyword_overlap")
    if overlap: dimensions["keyword_overlap"] = minmax(median(overlap), 0, 1, reverse=True)
    gate = multiple_products and len(dimensions) >= 2
    if gate: status = "SUFFICIENT"
    elif current and (multiple_products or dimensions): status = "PARTIAL"
    elif all_comp: status = "INSUFFICIENT"
    else: status = "UNKNOWN"
    score = round(sum(dimensions.values()) / len(dimensions), 2) if len(dimensions) >= 2 else None
    confidence = round(min(100, len(dimensions) * 20 + (20 if multiple_products else 0)) * (sum(STRENGTH[r.confidence] for r in current) / max(1, len(current))), 2) if current else 0.0
    if gate: reason = f"Observed multiple Amazon UAE competitors across {len(dimensions)} competition dimensions."
    elif not all_comp: reason = "Competition evidence is unknown; missing metrics are not treated as favorable."
    elif not current: reason = "Competition evidence is insufficient because available observations are stale, aging, or not Amazon UAE marketplace facts."
    elif not multiple_products: reason = "Competition evidence is insufficient: multiple competing Amazon UAE products were not observed."
    else: reason = f"Competition evidence is partial: only {len(dimensions)} useful dimension(s), at least two required."
    return {"score": score, "confidence": confidence, "status": status, "gate": gate, "gate_reason": reason, "dimensions": dimensions, "evidence_ids": [r.id for r in current]}


def _risk_component(records: list[EvidenceRecord], as_of: datetime, fresh_cfg: dict[str, Any]) -> dict[str, Any]:
    risk_records = [r for r in records if r.metric_name in RISK_METRICS and r.metric_value is not None and str(r.metric_value).upper() != "UNKNOWN" and _fresh(r, as_of, fresh_cfg) != EvidenceFreshness.STALE]
    values = _numeric(risk_records, "risk_score")
    regulatory = [str(r.metric_value).upper() for r in risk_records if r.metric_name == "regulatory_risk"]
    score = median(values) if values else (80 if "HIGH" in regulatory else 50 if "MEDIUM" in regulatory else 20 if "LOW" in regulatory else None)
    gate = score is not None
    status = "SUFFICIENT" if gate else "UNKNOWN"
    confidence = round(max((STRENGTH[r.confidence] for r in risk_records), default=0) * 100, 2)
    reasons=[str(r.notes or r.metric_value) for r in risk_records if r.metric_name in {"regulatory_risk","risk_score"}]
    urls=list(dict.fromkeys(r.source_url for r in risk_records if r.source_url))
    return {"score": round(score, 2) if score is not None else None, "confidence": confidence, "status": status, "gate": gate, "gate_reason": "Risk evaluation is available." if gate else "Risk evaluation is missing or unknown.", "evidence_ids": [r.id for r in risk_records], "risk_reasons": reasons, "risk_source_urls": urls}


def _source_status(records: list[EvidenceRecord]) -> dict[str, str]:
    used = {"Codex live web search": False, "Amazon UAE official pages": False, "SerpApi": False, "DataForSEO": False, "Rainforest": False, "Amazon SP-API": False}
    for record in records:
        host = urlparse(record.source_url or "").hostname or ""
        if record.source_provider == "codex_web": used["Codex live web search"] = True
        if host == "sell.amazon.ae" or host.endswith(".sell.amazon.ae") or record.source_provider == "amazon_public": used["Amazon UAE official pages"] = True
        if record.source_provider == "serpapi": used["SerpApi"] = True
        if record.source_provider == "dataforseo": used["DataForSEO"] = True
        if record.source_provider == "rainforest": used["Rainforest"] = True
        if record.source_provider == "sp_api": used["Amazon SP-API"] = True
    return {name: "USED" if is_used else ("NOT_CONFIGURED" if name in {"SerpApi", "DataForSEO", "Rainforest", "Amazon SP-API"} else "AVAILABLE_NOT_USED") for name, is_used in used.items()}


def recommendation_tier(candidate_type: str, gates: dict[str, dict[str, Any]], preliminary: float | None, validated: float | None, confidence: float, risk_score: float | None, constraint_rejected: bool, minimum_recommendation_score: float = 65, commercial_classification: str = "CORE_MARKET_OPPORTUNITY") -> str:
    if candidate_type == "BUNDLE_HYPOTHESIS": return "BUNDLE_HYPOTHESIS"
    if commercial_classification == "PREMIUM_POSITIONING_HYPOTHESIS": return "PREMIUM_POSITIONING_HYPOTHESIS"
    if constraint_rejected: return "REJECTED_CONSTRAINT"
    if risk_score is not None and risk_score >= 70: return "HIGH_RISK"
    if validated is not None and confidence >= 60:
        return "VALIDATED_CANDIDATE" if validated >= minimum_recommendation_score else "VALIDATED_WEAK_OPPORTUNITY"
    if preliminary is not None and any(g["gate"] for g in gates.values()): return "PROMISING_BUT_UNVALIDATED"
    return "EVIDENCE_GAP"


def canonical_funnel(raw_funnel: dict[str, Any], analyses: list[dict[str, Any]]) -> dict[str, int]:
    generated = int(raw_funnel.get("generated", raw_funnel.get("ideas_generated", raw_funnel.get("researched", len(analyses)))))
    screened = min(generated, int(raw_funnel.get("screened", len(analyses))))
    evidence_backed = min(screened, sum(any(v["status"] not in {"UNKNOWN"} for v in a["components"].values()) for a in analyses))
    serpapi_validated = min(evidence_backed, sum(bool(a.get("serpapi_keywords")) for a in analyses))
    validated = min(evidence_backed, sum(bool(a.get("technically_validated")) for a in analyses))
    strong = min(validated, sum(bool(a.get("qualified_strong_opportunity")) for a in analyses))
    finalists = strong
    bundles = sum(a["candidate_type"] == "BUNDLE_HYPOTHESIS" for a in analyses)
    return {"generated": generated, "screened": screened, "web_evidence_backed": evidence_backed, "evidence_backed": evidence_backed, "serpapi_validated": serpapi_validated, "price_gate_passed": sum(a["gates"]["price"]["gate"] for a in analyses), "demand_gate_passed": sum(a["gates"]["demand"]["gate"] for a in analyses), "competition_gate_passed": sum(a["gates"]["competition"]["gate"] for a in analyses), "risk_gate_passed": sum(a["gates"]["risk"]["gate"] for a in analyses), "technically_validated": validated, "strong_opportunities": strong, "validated": validated, "bundle_hypotheses": bundles, "finalists": finalists}


def validate_funnel_invariants(funnel: dict[str, int]) -> None:
    evidence_backed = funnel.get("web_evidence_backed", funnel.get("evidence_backed", 0))
    if not (funnel["generated"] >= funnel["screened"] >= evidence_backed >= funnel["validated"] >= funnel["finalists"]):
        raise ValueError("Canonical funnel invariant violated")


def analyze_evidence_bundle(raw: dict[str, Any], records: list[EvidenceRecord], *, generated_at: datetime | None = None) -> list[dict[str, Any]]:
    generated_at = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scoring = load_scoring_config(); fresh_cfg = load_freshness_config(); commercial_cfg = load_commercial_config()["price_gate"]
    by_niche: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if record.niche: by_niche[record.niche].append(record)
    products_by_niche: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product in raw["products"]:
        if product.get("niche"): products_by_niche[product["niche"]].append(product)
    results: list[dict[str, Any]] = []
    filters = raw["research_run"].get("filters", {}); minimum = filters.get("price_min_aed"); maximum = filters.get("price_max_aed")
    for niche in sorted(set(by_niche) | set(products_by_niche)):
        evidence = by_niche[niche]; raw_products = products_by_niche[niche]; products, asin_audit = canonical_products_by_asin(raw_products); product = products[0] if products else {}
        candidate_type = _candidate_type(product)
        has_segment_data = any(p.get("commercial_segment_status") for p in products)
        comparable_products = [p for p in products if p.get("commercial_segment_status") == "COMPARABLE"] if has_segment_data else products
        comparable_asins = {str(p["asin"]) for p in comparable_products if p.get("asin")}
        # Per-ASIN SerpApi evidence must follow the persisted commercial classification.
        # Old/non-SerpApi evidence remains loadable without inventing a segment.
        segment_evidence = [r for r in evidence if r.source_provider != "serpapi" or (r.asin is not None and r.asin in comparable_asins)] if has_segment_data else evidence
        statistical_segment_evidence = canonical_statistical_records(segment_evidence)
        price_records = [r for r in canonical_statistical_records(evidence) if r.metric_name in {"current_price_aed", "observed_market_price_aed"} and isinstance(r.metric_value, (int, float))]
        amazon_price_records = [r for r in price_records if _effective_relevance(r) == MarketRelevance.AMAZON_UAE]
        comparable_amazon_price_records = [r for r in amazon_price_records if not has_segment_data or (r.asin is not None and r.asin in comparable_asins)]
        current_amazon_price_records = [r for r in amazon_price_records if _fresh(r, generated_at, fresh_cfg) == EvidenceFreshness.CURRENT]
        comparable_current_price_records = [r for r in current_amazon_price_records if not has_segment_data or (r.asin is not None and r.asin in comparable_asins)]
        observed_amazon_prices = [float(r.metric_value) for r in amazon_price_records]
        current_amazon_prices = [float(r.metric_value) for r in current_amazon_price_records]
        comparable_current_prices = [float(r.metric_value) for r in comparable_current_price_records]
        external_prices = [float(r.metric_value) for r in price_records if _effective_relevance(r) == MarketRelevance.UAE_RETAIL]
        observed_market_price = median(observed_amazon_prices) if observed_amazon_prices else None
        proposed = product.get("proposed_selling_price_aed") or product.get("bundle_hypothesis_price_aed")
        if candidate_type == "BUNDLE_HYPOTHESIS" and proposed is None:
            proposed = _legacy_fee_basis(evidence) or product.get("current_price_aed")
        fee_basis = product.get("fee_calculation_price_aed") or _legacy_fee_basis(evidence)
        if fee_basis is None and candidate_type == "OBSERVED_MARKET_OPPORTUNITY" and comparable_current_prices: fee_basis = median(comparable_current_prices)
        price_decision = evaluate_price_gate(comparable_current_prices, minimum, maximum, minimum_sample_size=int(commercial_cfg["minimum_comparable_products"]), minimum_in_target_band_ratio=float(commercial_cfg["minimum_in_target_band_ratio"]))
        comparable_in_band = price_decision.in_target_band_count
        comparable_ratio = price_decision.in_target_band_ratio or 0.0
        comparable_median = price_decision.median_price_aed
        price_in_band = price_decision.gate
        price_gate = candidate_type == "OBSERVED_MARKET_OPPORTUNITY" and price_in_band
        if candidate_type != "OBSERVED_MARKET_OPPORTUNITY": price_reason = "Hypothetical bundle/differentiation price cannot satisfy the observed Amazon UAE price gate."
        elif comparable_current_prices: price_reason = price_decision.reason
        elif amazon_price_records: price_reason = "Amazon UAE price evidence exists, but it is not current enough to satisfy the price gate."
        elif external_prices: price_reason = "Only external UAE retail prices are available; they are context and cannot satisfy the Amazon UAE price gate."
        else: price_reason = "No current credible Amazon UAE price observation is available."
        demand = _demand_component(segment_evidence, generated_at, fresh_cfg)
        competition = _competition_component(statistical_segment_evidence, comparable_products, comparable_current_prices, generated_at, fresh_cfg)
        risk = _risk_component(evidence, generated_at, fresh_cfg)
        fee_records = [r for r in evidence if r.metric_name in {"estimated_referral_fee_aed", "total_estimated_amazon_fees_aed"} and isinstance(r.metric_value, (int, float))]
        preferred_fee = choose_preferred(fee_records); known_fee = float(preferred_fee.metric_value) if preferred_fee else None
        economics = calculate_candidate_economics(niche, fee_basis)
        economics_raw = economics.get("score", {}).get("raw")
        margin_score = economics_raw if economics_raw is not None else (round(clamp(100 - known_fee / fee_basis * 180), 2) if known_fee is not None and fee_basis else None)
        price_score = minmax(fee_basis, 40, 200, missing=0) if fee_basis is not None else None
        brands = {str(r.metric_value).lower() for r in evidence if r.metric_name == "brand" and r.metric_value}
        differentiation = round(min(85, 30 + len(brands) * 5 + len({r.keyword for r in evidence if r.keyword}) * 3), 2) if evidence else None
        factors = {"demand": demand["score"], "competition_attractiveness": competition["score"], "margin_potential": margin_score, "price_attractiveness": price_score, "risk_attractiveness": None if risk["score"] is None else 100-risk["score"], "differentiation_potential": differentiation}
        preliminary = opportunity_score(factors, scoring["weights"]) if any(v is not None for v in factors.values()) else None
        gates = {"price": {"gate": price_gate, "reason": price_reason}, "demand": {"gate": demand["gate"], "reason": demand["gate_reason"]}, "competition": {"gate": competition["gate"], "reason": competition["gate_reason"]}, "risk": {"gate": risk["gate"], "reason": risk["gate_reason"]}}
        required_pass = all(g["gate"] for g in gates.values())
        validated = preliminary if required_pass else None
        component_confidences = [demand["confidence"], competition["confidence"], risk["confidence"], 80.0 if price_gate else 0.0]
        overall_confidence = round(sum(component_confidences) / len(component_confidences), 2)
        score_breakdown = opportunity_score_breakdown(factors, scoring["weights"], confidence=overall_confidence) if preliminary is not None else None
        if score_breakdown is not None: score_breakdown["final_validated_opportunity_score"] = validated
        confidence_gate = overall_confidence >= scoring["research_gates"]["top_3_minimum_confidence"]
        gates["confidence"] = {"gate": confidence_gate, "reason": "Overall data confidence meets the 60% sourcing threshold." if confidence_gate else f"Overall data confidence {overall_confidence}% is below the required 60%."}
        premium_prices = [float(p["current_price_aed"]) for p in products if p.get("positioning") == "PREMIUM" and isinstance(p.get("current_price_aed"),(int,float)) and (minimum is None or float(p["current_price_aed"]) >= minimum) and (maximum is None or float(p["current_price_aed"]) <= maximum)]
        below_floor_with_premium_tail = not price_gate and comparable_median is not None and minimum is not None and comparable_median < minimum and (comparable_in_band > 0 or bool(premium_prices))
        commercial_classification = "PREMIUM_POSITIONING_HYPOTHESIS" if below_floor_with_premium_tail else "CORE_MARKET_OPPORTUNITY"
        rejected = candidate_type == "OBSERVED_MARKET_OPPORTUNITY" and bool(current_amazon_prices) and not price_in_band
        minimum_recommendation_score = float(scoring["research_gates"].get("minimum_recommendation_score", 65))
        tier = recommendation_tier(candidate_type, gates, preliminary, validated, overall_confidence, risk["score"], rejected, minimum_recommendation_score, commercial_classification)
        technically_validated = required_pass and confidence_gate
        qualified_strong = technically_validated and validated is not None and validated >= minimum_recommendation_score
        freshnesses = [_fresh(r, generated_at, fresh_cfg) for r in evidence]
        aggregate_freshness = "CURRENT" if any(x == EvidenceFreshness.CURRENT for x in freshnesses) else "AGING" if any(x == EvidenceFreshness.AGING for x in freshnesses) else "STALE" if freshnesses else "UNKNOWN"
        component_freshness = {
            "price": _component_freshness(comparable_amazon_price_records, generated_at, fresh_cfg),
            "demand": _component_freshness([r for r in segment_evidence if r.metric_name in DEMAND_METRICS], generated_at, fresh_cfg),
            "competition": _component_freshness([r for r in segment_evidence if r.metric_name in COMPETITION_METRICS], generated_at, fresh_cfg),
            "risk": _component_freshness([r for r in evidence if r.metric_name in RISK_METRICS], generated_at, fresh_cfg),
        }
        current_stats = price_statistics(current_amazon_prices); comparable_stats = price_statistics(comparable_current_prices)
        representative_asins = list(dict.fromkeys(str(p.get("asin")) for p in comparable_products if p.get("asin")))
        priced_comparables = [p for p in comparable_products if p.get("asin") and isinstance(p.get("current_price_aed"),(int,float))]
        if fee_basis and priced_comparables:
            representative = min(priced_comparables, key=lambda p: abs(float(p["current_price_aed"])-float(fee_basis)))
            economics["representative_asin"] = representative["asin"]
            economics["representative_price_aed"] = float(representative["current_price_aed"])
            economics["representative_selection_reason"] = "Comparable ASIN with current price closest to the comparable-segment median; no unrelated premium/cheap variant was substituted."
        serpapi_keywords = list(dict.fromkeys(str(r.keyword) for r in evidence if r.source_provider == "serpapi" and r.keyword))
        ratings = _numeric([r for r in statistical_segment_evidence if r.source_provider == "serpapi" and _fresh(r, generated_at, fresh_cfg) == EvidenceFreshness.CURRENT], "rating")
        reviews = _numeric([r for r in statistical_segment_evidence if r.source_provider == "serpapi" and _fresh(r, generated_at, fresh_cfg) == EvidenceFreshness.CURRENT], "review_count")
        sponsored_values = [bool(r.metric_value) for r in statistical_segment_evidence if r.source_provider == "serpapi" and r.metric_name == "sponsored_status" and _fresh(r, generated_at, fresh_cfg) == EvidenceFreshness.CURRENT]
        sponsored_complete = bool(representative_asins) and len(sponsored_values) >= len({p.get('asin') for p in comparable_products if p.get('asin')})
        exact_prices=[float(p["current_price_aed"]) for p in products if p.get("target_match_quality")=="EXACT_TARGET" and isinstance(p.get("current_price_aed"),(int,float))]
        close_prices=[float(p["current_price_aed"]) for p in products if p.get("target_match_quality")=="CLOSE_VARIANT" and isinstance(p.get("current_price_aed"),(int,float))]
        scenarios = uncertain_fee_scenarios(float(fee_basis), known_fee, (8,14,22)) if fee_basis and known_fee is not None else None
        results.append({
            "niche": niche, "products": products, "evidence": evidence, "candidate_type": candidate_type, "commercial_opportunity_classification": commercial_classification,
            "observed_market_price_aed": observed_market_price, "observed_price_min_aed": min(observed_amazon_prices) if observed_amazon_prices else None,
            "observed_price_max_aed": max(observed_amazon_prices) if observed_amazon_prices else None, "external_uae_retail_prices_aed": external_prices,
            "proposed_selling_price_aed": proposed, "bundle_hypothesis_price_aed": proposed if candidate_type == "BUNDLE_HYPOTHESIS" else None,
            "fee_calculation_price_aed": fee_basis, "known_fee_aed": known_fee, "fee_category_assumption": preferred_fee.notes if preferred_fee else None,
            "fee_source": preferred_fee.source_url if preferred_fee else None, "fee_observed_at": preferred_fee.observed_at if preferred_fee else None,
            "fee_status": "estimated" if preferred_fee and preferred_fee.is_estimate else "observed" if preferred_fee else "unknown",
            "known_fee_components": ["referral fee"] if known_fee is not None else [], "unknown_fee_components": ["actual supplier cost", "observed packaged dimensions/weight", "verified freight quote"], "fee_scenarios": scenarios, "economics": economics,
            "components": {"demand": demand, "competition": competition, "risk": risk}, "demand_score": demand["score"], "demand_status": demand["status"], "demand_confidence": demand["confidence"],
            "competition_score": competition["score"], "competition_status": competition["status"], "competition_confidence": competition["confidence"],
            "risk_score": risk["score"], "risk_status": risk["status"], "risk_confidence": risk["confidence"], "factors": factors,
            "preliminary_opportunity_score": preliminary, "validated_opportunity_score": validated, "opportunity_score": preliminary, "score_breakdown": score_breakdown,
            "data_confidence_score": overall_confidence, "recommendation_tier": tier, "technically_validated": technically_validated, "qualified_strong_opportunity": qualified_strong, "gates": gates, "evidence_freshness": aggregate_freshness,
            "component_freshness": component_freshness, "representative_asins": representative_asins[:12], "serpapi_keywords": serpapi_keywords,
            "relevance_summary": {"total_serpapi_results": int(sum(_numeric(evidence,"total_serpapi_results") or [0])), "target_results": int(sum(_numeric(evidence,"target_product_results") or [0])+sum(_numeric(evidence,"target_is_accessory_results") or [0])), "exact_results": int(sum(_numeric(evidence,"exact_results") or [0])), "close_variants": int(sum(_numeric(evidence,"close_variants") or [0])), "accessory_to_target_exclusions": int(sum(_numeric(evidence,"accessory_to_target_exclusions") or [0])), "excluded_accessories": int(sum(_numeric(evidence,"excluded_accessories") or [0])), "excluded_wrong_products": int(sum(_numeric(evidence,"excluded_wrong_products") or [0])), "ambiguous_results": int(sum(_numeric(evidence,"ambiguous_results") or [0])), "exact_target_price_sample": exact_prices, "close_variant_price_sample": close_prices, "combined_validated_price_sample": exact_prices+close_prices},
            "structured_metrics": {**asin_audit, "relevant_result_count": len({p.get('asin') for p in products if p.get('asin')}), "comparable_result_count": len({p.get('asin') for p in comparable_products if p.get('asin')}), "amazon_uae_price_sample_size": len(current_amazon_prices), "current_price_min_aed": min(current_amazon_prices) if current_amazon_prices else None, "current_price_median_aed": current_stats.get("median"), "current_price_max_aed": max(current_amazon_prices) if current_amazon_prices else None, "comparable_sample_size": len(comparable_current_prices), "comparable_price_min_aed": min(comparable_current_prices) if comparable_current_prices else None, "comparable_price_p25_aed": comparable_stats.get("p25"), "comparable_price_median_aed": comparable_stats.get("median"), "comparable_price_mean_aed": comparable_stats.get("mean"), "comparable_price_p75_aed": comparable_stats.get("p75"), "comparable_price_max_aed": max(comparable_current_prices) if comparable_current_prices else None, "comparable_in_target_band_count": comparable_in_band, "comparable_in_target_band_ratio": comparable_ratio if comparable_current_prices else None, "price_gate_minimum_comparable_products": commercial_cfg["minimum_comparable_products"], "price_gate_minimum_in_band_ratio": commercial_cfg["minimum_in_target_band_ratio"], "rating_sample_size": len(ratings), "median_rating": median(ratings) if ratings else None, "review_sample_size": len(reviews), "median_reviews": median(reviews) if reviews else None, "p75_reviews": percentile(reviews,.75) if reviews else None, "sponsored_sample_size": len(sponsored_values), "sponsored_count": sum(sponsored_values) if sponsored_values else None, "sponsored_density": sum(sponsored_values)/len(sponsored_values) if sponsored_complete else None, "unique_brand_count": len({str(r.metric_value).lower() for r in statistical_segment_evidence if r.metric_name == 'brand' and r.metric_value}), "top_brand_share": max(Counter(str(r.metric_value).lower() for r in statistical_segment_evidence if r.metric_name == 'brand' and r.metric_value).values())/max(1,len([r for r in statistical_segment_evidence if r.metric_name == 'brand' and r.metric_value])) if any(r.metric_name == 'brand' and r.metric_value for r in statistical_segment_evidence) else None, "bought_last_month_observations": [r.metric_value for r in statistical_segment_evidence if r.metric_name == 'bought_last_month_raw']},
            "final_top_10_eligible": qualified_strong, "top_3_to_source_eligible": qualified_strong and candidate_type == "OBSERVED_MARKET_OPPORTUNITY",
            "remaining_unknowns": [name for name, value in (("Amazon UAE price", observed_market_price), ("fee calculation price", fee_basis), ("demand score", demand["score"]), ("competition score", competition["score"]), ("risk score", risk["score"])) if value is None],
        })
    return sorted(results, key=lambda x: (x["validated_opportunity_score"] is not None, x["preliminary_opportunity_score"] or -1), reverse=True)


def source_status_from_evidence(records: list[EvidenceRecord]) -> dict[str, str]: return _source_status(records)


def evidence_cutoff(records: list[EvidenceRecord], generated_at: datetime) -> str:
    times = [parse_aware_datetime(r.observed_at, "observed_at") for r in records] + [parse_aware_datetime(r.retrieved_at, "retrieved_at") for r in records]
    cutoff = min(max(times), generated_at.astimezone(timezone.utc)) if times else generated_at.astimezone(timezone.utc)
    return cutoff.isoformat().replace("+00:00", "Z")


def historical_changes(db: ScoutDatabase, asin: str | None, niche: str | None, now: str) -> dict[str, float | None]:
    result = {key: None for key in ("price_change_7d", "price_change_30d", "review_count_change", "rating_change", "rank_change", "competitor_count_change", "search_volume_change")}
    filters: list[str] = []; params: list[str] = []
    if asin: filters.append("asin=?"); params.append(asin)
    elif niche: filters.append("niche=?"); params.append(niche)
    else: return result
    mapping = {"current_price_aed":"price_change_7d", "review_count":"review_count_change", "rating":"rating_change", "bestseller_rank":"rank_change", "visible_competing_products":"competitor_count_change", "amazon_search_volume":"search_volume_change"}
    with db.connect() as connection:
        for metric, output in mapping.items():
            rows = connection.execute(f"SELECT metric_value_json,observed_at FROM evidence_records WHERE {' AND '.join(filters)} AND metric_name=? ORDER BY observed_at", (*params, metric)).fetchall()
            values = [(json.loads(row[0]), row[1]) for row in rows if isinstance(json.loads(row[0]), (int,float))]
            if len(values) >= 2: result[output] = round(float(values[-1][0])-float(values[-2][0]),2)
    return result
