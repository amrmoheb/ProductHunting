from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

VERSION = "V1.4C"
CANDIDATES = (
    "long handle baseboard cleaning tool",
    "wood crochet blocking board",
    "washable ceiling fan blade sleeve duster",
    "adjustable airplane foot hammock",
    "foldable calf slant board",
)
DEFAULT_V13 = Path("reports/2026-08-12-075921-resumed-diversified-hunt-v1.3-economics-audit.json")
DEFAULT_V14B = Path("reports/2026-08-14-034240-v1.json")
DEFAULT_V14B1 = Path("reports/2026-08-14-035943-v1.json")
DEFAULT_V14B2 = Path("reports/2026-08-14-041009-v1.json")

EVIDENCE_STATES = ("OBSERVED_POSITIVE", "OBSERVED_NEGATIVE", "UNKNOWN", "NOT_SUPPORTED", "NOT_RUN", "STALE")
PROVIDER_ROLES = {
    "dataforseo_bulk_search_volume": {"role": "SUPPLEMENTAL_ONLY", "reason": "Arabic-only partial coverage, English not confirmed, and sparse absolute volumes cannot represent total UAE demand."},
    "dataforseo_ranked_keywords": {"role": "SUPPLEMENTAL_COMPETITION_SIGNAL", "poc_rows": 3, "poc_conclusion": "SPARSE_BUT_USABLE"},
    "dataforseo_product_competitors": {"role": "COMPETITION_INTELLIGENCE_SIGNAL", "poc_rows": 10, "poc_conclusion": "USEFUL"},
    "serpapi_amazon_ae": {"role": "PRIMARY_CURRENT_PUBLIC_MARKET_SIGNAL"},
    "v1_3_economics": {"role": "KEEP_UNCHANGED"},
}
DEMAND_WEIGHTS = {"listing_activity": .35, "review_activity": .30, "search_evidence": .20, "breadth_freshness": .15}
COMPETITION_WEIGHTS = {"comparable_density": .30, "review_barrier": .25, "market_concentration": .15, "dataforseo_competitors": .20, "dataforseo_ranked_keywords": .10}
CURRENT_OPPORTUNITY_WEIGHTS = {"demand": .30, "competition_attractiveness": .20, "margin_potential": .20, "price_attractiveness": .10, "risk_attractiveness": .10, "differentiation_potential": .10}
PROPOSED_OPPORTUNITY_WEIGHTS = {"demand": .30, "competition": .25, "economics": .35, "risk": .10}


def load_artifacts(v13_path: Path = DEFAULT_V13, v14b_path: Path = DEFAULT_V14B, v14b1_path: Path = DEFAULT_V14B1, v14b2_path: Path = DEFAULT_V14B2) -> dict[str, Any]:
    """Read completed local artifacts only. This module imports no provider source."""
    return {name: json.loads(path.read_text(encoding="utf-8")) for name, path in {
        "v13": v13_path, "v14b": v14b_path, "v14b1": v14b1_path, "v14b2": v14b2_path,
    }.items()}


def _round(value: float | None) -> float | None:
    return None if value is None else round(max(0.0, min(100.0, value)), 2)


def _band(score: float | None) -> str:
    if score is None: return "UNKNOWN"
    if score >= 80: return "EXCEPTIONAL"
    if score >= 65: return "STRONG"
    if score >= 45: return "MODERATE"
    if score >= 25: return "LIMITED"
    return "WEAK"


def weighted_score(families: dict[str, dict[str, Any]], weights: dict[str, float]) -> dict[str, Any]:
    """Fixed denominator: missing families add zero, never trigger weight redistribution."""
    arithmetic = []
    numerator = 0.0
    observed_weight = 0.0
    for name, weight in weights.items():
        family = families[name]
        score = family.get("score")
        observed = isinstance(score, (int, float)) and not isinstance(score, bool)
        contribution = float(score) * weight if observed else 0.0
        numerator += contribution
        observed_weight += weight if observed else 0.0
        arithmetic.append({"family": name, "score": score, "weight": weight, "contribution": round(contribution, 4), "status": family["status"], "missing_behavior": "ZERO_CONTRIBUTION_NO_REDISTRIBUTION" if not observed else "OBSERVED"})
    return {"score": _round(numerator), "available_weight": round(observed_weight, 4), "missing_weight": round(1-observed_weight, 4), "denominator": 1.0, "formula": "sum(observed_family_score * fixed_family_weight); missing contribution = 0; weights are not redistributed", "arithmetic": arithmetic}


def _signal(score: float | None, status: str, facts: dict[str, Any]) -> dict[str, Any]:
    assert status in EVIDENCE_STATES
    return {"score": _round(score), "status": status, "facts": facts}


def _deduplicated_products(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    by_asin: dict[str, dict[str, Any]] = {}
    for product in analysis.get("products") or []:
        asin = product.get("asin")
        if asin and asin not in by_asin:
            by_asin[asin] = product
    return list(by_asin.values())


def _arabic_row(candidate: str, v14b1: dict[str, Any]) -> dict[str, Any] | None:
    return next((row for row in v14b1.get("normalized_keyword_rows", []) if row.get("candidate") == candidate), None)


def demand_families(analysis: dict[str, Any], v14b1: dict[str, Any], *, include_arabic: bool = True, review_weight_factor: float = 1.0) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    metrics = analysis["structured_metrics"]
    relevance = analysis["relevance_summary"]
    comparable = int(metrics.get("comparable_result_count") or 0)
    exact = int(relevance.get("exact_results") or 0)
    target = int(relevance.get("target_results") or 0)
    exact_share = exact / target if target else 0
    listing = min(comparable / 60, 1) * 70 + exact_share * 30

    med = metrics.get("median_reviews")
    p75 = metrics.get("p75_reviews")
    if med is None or p75 is None:
        reviews = _signal(None, "UNKNOWN", {"median_reviews": med, "p75_reviews": p75})
    else:
        review_score = 55 * min(math.log1p(max(0, med)) / math.log1p(500), 1) + 45 * min(math.log1p(max(0, p75)) / math.log1p(2000), 1)
        reviews = _signal(review_score, "OBSERVED_POSITIVE" if review_score >= 45 else "OBSERVED_NEGATIVE", {"median_reviews": med, "p75_reviews": p75, "method": "log-scaled median (55%) plus p75 (45%); no maximum-listing input"})

    demand = analysis["components"]["demand"]
    observations = int(demand.get("observation_count") or 0)
    weak = set(demand.get("weak_dimensions") or [])
    serp_score = min(observations / 150, 1) * 70 + (15 if "repeat_keyword_visibility" in weak else 0) + (15 if demand.get("purchase_signal_count", 0) else 0)
    row = _arabic_row(analysis["niche"], v14b1) if include_arabic else None
    arabic_numeric = row and row.get("volume_status") in {"NUMERIC_VOLUME", "ZERO_VOLUME"}
    arabic_score = min(math.log1p(max(0, row["search_volume"])) / math.log1p(100), 1) * 100 if arabic_numeric else None
    search_score = serp_score * .90 + (arabic_score * .10 if arabic_score is not None else 0)
    search = _signal(search_score, "OBSERVED_POSITIVE" if search_score >= 45 else "OBSERVED_NEGATIVE", {"serpapi_subscore": _round(serp_score), "serpapi_weight_within_family": .90, "arabic_subscore": _round(arabic_score), "arabic_weight_within_family": .10, "arabic_volume_status": row.get("volume_status") if row else "NOT_RUN", "arabic_volume": row.get("search_volume") if row else None, "arabic_missing_behavior": "zero contribution; never interpreted as zero demand"})

    unique_asins = len(_deduplicated_products(analysis))
    relevance_ratio = target / max(1, int(relevance.get("total_serpapi_results") or 0))
    freshness = 20 if analysis.get("evidence_freshness") == "CURRENT" else 0
    breadth_score = min(unique_asins / 60, 1) * 50 + relevance_ratio * 30 + freshness
    breadth = _signal(breadth_score, "OBSERVED_POSITIVE" if breadth_score >= 45 else "OBSERVED_NEGATIVE", {"unique_asins": unique_asins, "target_relevance_ratio": round(relevance_ratio, 4), "freshness_points": freshness})
    families = {"listing_activity": _signal(listing, "OBSERVED_POSITIVE" if listing >= 45 else "OBSERVED_NEGATIVE", {"comparable_count": comparable, "exact_share": round(exact_share, 4)}), "review_activity": reviews, "search_evidence": search, "breadth_freshness": breadth}
    weights = dict(DEMAND_WEIGHTS)
    if review_weight_factor != 1:
        changed = weights["review_activity"] * review_weight_factor
        delta = changed - weights["review_activity"]
        weights["review_activity"] = changed
        weights["listing_activity"] -= delta
    return families, weights


def _dataforseo_competitor_signal(candidate: str, v14b2: dict[str, Any], include: bool) -> dict[str, Any]:
    if candidate != v14b2.get("candidate") or not include:
        return _signal(None, "NOT_RUN", {"rows": 0, "reason": "POC queried one candidate only" if include else "removed by sensitivity scenario"})
    outcome = v14b2.get("endpoint_outcomes", {}).get("product_competitors", {}).get("status")
    if outcome == "UNSUPPORTED": return _signal(None, "NOT_SUPPORTED", {"rows": 0})
    rows = [r for r in v14b2.get("product_competitors", []) if r.get("competitor_asin") and r.get("competitor_asin") != v14b2.get("representative_asin")]
    unique = {r["competitor_asin"]: r for r in rows}
    if outcome != "SUCCEEDED" or not unique: return _signal(None, "UNKNOWN", {"rows": len(rows)})
    values = list(unique.values())
    intersections = [r["keyword_intersections"] for r in values if isinstance(r.get("keyword_intersections"), (int, float))]
    positions = [r["average_position"] for r in values if isinstance(r.get("average_position"), (int, float))]
    difficulty = min(len(values) / 20, 1) * 50 + min((median(intersections) if intersections else 0) / 5, 1) * 30 + (sum(p <= 10 for p in positions) / len(positions) * 20 if positions else 0)
    return _signal(100-difficulty, "OBSERVED_POSITIVE" if 100-difficulty >= 50 else "OBSERVED_NEGATIVE", {"unique_external_competitors": len(values), "median_keyword_intersections": median(intersections) if intersections else None, "median_average_position": median(positions) if positions else None})


def _dataforseo_ranked_signal(candidate: str, v14b2: dict[str, Any], include: bool) -> dict[str, Any]:
    if candidate != v14b2.get("candidate") or not include: return _signal(None, "NOT_RUN", {"rows": 0})
    outcome = v14b2.get("endpoint_outcomes", {}).get("ranked_keywords", {}).get("status")
    if outcome == "UNSUPPORTED": return _signal(None, "NOT_SUPPORTED", {"rows": 0})
    rows = v14b2.get("ranked_keywords", [])
    positions = [r["organic_position"] for r in rows if isinstance(r.get("organic_position"), (int, float))]
    if outcome != "SUCCEEDED" or not positions: return _signal(None, "UNKNOWN", {"rows": len(rows)})
    breadth = min(len(rows) / 10, 1)
    incumbent_visibility = max(0, 1-min(median(positions), 50)/50)
    attractiveness = 100-(60*incumbent_visibility+40*breadth)
    return _signal(attractiveness, "OBSERVED_POSITIVE" if attractiveness >= 50 else "OBSERVED_NEGATIVE", {"keyword_rows": len(rows), "median_organic_position": median(positions), "role": "SUPPLEMENTAL_ONLY"})


def competition_families(analysis: dict[str, Any], v14b2: dict[str, Any], *, include_dataforseo: bool = True, density_weight_factor: float = 1.0) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    products = _deduplicated_products(analysis)
    comparable = len(products)
    density = max(0, 100-min(comparable/80, 1)*100)
    reviews = [p.get("reviews") for p in products if isinstance(p.get("reviews"), (int, float)) and p.get("reviews") >= 0]
    if reviews:
        med, p75 = analysis["structured_metrics"].get("median_reviews"), analysis["structured_metrics"].get("p75_reviews")
        barrier = 100-(55*min(math.log1p(med or 0)/math.log1p(500), 1)+45*min(math.log1p(p75 or 0)/math.log1p(2000), 1))
        total = sum(reviews)
        concentration = 100*(1-(sum(sorted(reviews, reverse=True)[:3])/total if total else 0))
        review_signal = _signal(barrier, "OBSERVED_POSITIVE" if barrier >= 50 else "OBSERVED_NEGATIVE", {"median_reviews": med, "p75_reviews": p75})
        concentration_signal = _signal(concentration, "OBSERVED_POSITIVE" if concentration >= 50 else "OBSERVED_NEGATIVE", {"top_three_review_share": round(1-concentration/100, 4), "basis": "deduplicated comparable ASIN review counts"})
    else:
        review_signal = _signal(None, "UNKNOWN", {"review_rows": 0})
        concentration_signal = _signal(None, "UNKNOWN", {"review_rows": 0})
    families = {
        "comparable_density": _signal(density, "OBSERVED_POSITIVE" if density >= 50 else "OBSERVED_NEGATIVE", {"unique_comparable_asins": comparable, "duplicate_asins_removed": len(analysis.get("products") or [])-comparable}),
        "review_barrier": review_signal,
        "market_concentration": concentration_signal,
        "dataforseo_competitors": _dataforseo_competitor_signal(analysis["niche"], v14b2, include_dataforseo),
        "dataforseo_ranked_keywords": _dataforseo_ranked_signal(analysis["niche"], v14b2, include_dataforseo),
    }
    weights = dict(COMPETITION_WEIGHTS)
    if density_weight_factor != 1:
        changed = weights["comparable_density"] * density_weight_factor
        delta = changed-weights["comparable_density"]
        weights["review_barrier"] -= delta
    return families, weights


def confidence_score(analysis: dict[str, Any], weighted: dict[str, Any], families: dict[str, dict[str, Any]], *, is_demand: bool) -> dict[str, Any]:
    unique_asins = len(_deduplicated_products(analysis))
    observed = sum(f["score"] is not None for f in families.values())
    source_count = 2 + int(any(name.startswith("dataforseo") and f["score"] is not None for name, f in families.items()))
    relevance = analysis["relevance_summary"].get("target_results", 0) / max(1, analysis["relevance_summary"].get("total_serpapi_results", 0))
    parts = {
        "available_weight": weighted["available_weight"]*40,
        "observation_count": min(unique_asins/30, 1)*20,
        "relevance": relevance*15,
        "freshness": 10 if analysis.get("evidence_freshness") == "CURRENT" else 0,
        "independent_sources": min(source_count/3, 1)*10,
        "provider_agreement": 5 if source_count >= 3 else 0,
    }
    if is_demand or source_count >= 3:
        parts["partial_language_penalty"] = -5
    score = sum(parts.values())
    return {"score": _round(score), "parts": {k: round(v, 2) for k, v in parts.items()}, "observed_family_count": observed, "family_count": len(families), "score_is_separate_from_market_score": True}


def _max_landed_25(economics: dict[str, Any]) -> float | None:
    return ((economics.get("scenarios") or {}).get("BASE") or {}).get("maximum_landed_cost_aed", {}).get("25")


def _opportunity(demand: float | None, competition: float | None, economics: float | None, risk_score: float | None, confidence_parts: dict[str, float | None]) -> dict[str, Any]:
    values = {"demand": demand, "competition": competition, "economics": economics, "risk": None if risk_score is None else 100-risk_score}
    arithmetic=[]; total=0; available=0
    for name, weight in PROPOSED_OPPORTUNITY_WEIGHTS.items():
        value=values[name]; contribution=(value or 0)*weight if value is not None else 0
        total+=contribution; available+=weight if value is not None else 0
        arithmetic.append({"component":name,"score":value,"weight":weight,"contribution":round(contribution,4),"missing_behavior":"ZERO_CONTRIBUTION_NO_REDISTRIBUTION" if value is None else "OBSERVED"})
    confidence=sum((confidence_parts.get(name) or 0)*weight for name,weight in PROPOSED_OPPORTUNITY_WEIGHTS.items())
    return {"score":_round(total),"confidence":_round(confidence),"available_weight":round(available,4),"formula":"sum(component * proposed fixed weight); UNKNOWN = zero contribution and reduced separate confidence","arithmetic":arithmetic}


def calibrate_candidate(analysis: dict[str, Any], v14b1: dict[str, Any], v14b2: dict[str, Any], *, include_arabic: bool=True, include_dataforseo: bool=True, review_weight_factor: float=1, density_weight_factor: float=1) -> dict[str, Any]:
    demand_signals,demand_weights=demand_families(analysis,v14b1,include_arabic=include_arabic,review_weight_factor=review_weight_factor)
    demand=weighted_score(demand_signals,demand_weights); demand_conf=confidence_score(analysis,demand,demand_signals,is_demand=True)
    competition_signals,competition_weights=competition_families(analysis,v14b2,include_dataforseo=include_dataforseo,density_weight_factor=density_weight_factor)
    competition=weighted_score(competition_signals,competition_weights); competition_conf=confidence_score(analysis,competition,competition_signals,is_demand=False)
    economics=copy.deepcopy(analysis["economics"]); economics_score=(economics.get("score") or {}).get("raw") if isinstance(economics.get("score"),dict) else economics.get("score")
    risk_conf=analysis.get("risk_confidence") or 0
    opportunity=_opportunity(demand["score"],competition["score"],economics_score,analysis.get("risk_score"),{"demand":demand_conf["score"],"competition":competition_conf["score"],"economics":economics.get("confidence",0),"risk":risk_conf})
    current={"demand_score":analysis.get("demand_score"),"demand_confidence":analysis.get("demand_confidence"),"demand_status":analysis.get("demand_status"),"competition_score":analysis.get("competition_score"),"competition_confidence":analysis.get("competition_confidence"),"competition_status":analysis.get("competition_status"),"opportunity_score":analysis.get("opportunity_score")}
    return {"candidate":analysis["niche"],"current":current,"proposed":{"demand_score":demand["score"],"demand_confidence":demand_conf["score"],"demand_evidence_status":_band(demand["score"]),"demand_evidence_breakdown":demand_signals,"demand_arithmetic":demand,"demand_confidence_arithmetic":demand_conf,"competition_score":competition["score"],"competition_confidence":competition_conf["score"],"competition_evidence_status":_band(competition["score"]),"competition_evidence_breakdown":competition_signals,"competition_arithmetic":competition,"competition_confidence_arithmetic":competition_conf,"opportunity_score":opportunity["score"],"overall_evidence_confidence":opportunity["confidence"],"opportunity_arithmetic":opportunity},"economics":economics,"economics_status":economics.get("status"),"max_landed_cost_25_aed":_max_landed_25(economics),"economics_source_sha256":hashlib.sha256(json.dumps(economics,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),"official_scores_unchanged":True}


def _ranking(items: list[dict[str, Any]], path: tuple[str, ...]) -> list[str]:
    def value(item):
        cursor=item
        for key in path: cursor=cursor[key]
        return cursor if cursor is not None else -1
    return [x["candidate"] for x in sorted(items,key=lambda x:(-value(x),CANDIDATES.index(x["candidate"])))]


def _sensitivity(base: list[dict[str, Any]], analyses: dict[str, Any], v14b1: dict[str, Any], v14b2: dict[str, Any]) -> dict[str, Any]:
    scenarios={
        "dataforseo_competition_removed": dict(include_dataforseo=False),
        "arabic_search_volume_removed": dict(include_arabic=False),
        "review_weight_minus_20pct": dict(review_weight_factor=.8),
        "review_weight_plus_20pct": dict(review_weight_factor=1.2),
        "comparable_density_weight_minus_20pct": dict(density_weight_factor=.8),
        "comparable_density_weight_plus_20pct": dict(density_weight_factor=1.2),
    }
    base_rank=_ranking(base,("proposed","opportunity_score")); results={}; max_shift=0
    for name,kwargs in scenarios.items():
        rows=[calibrate_candidate(analyses[c],v14b1,v14b2,**kwargs) for c in CANDIDATES]
        rank=_ranking(rows,("proposed","opportunity_score")); shifts={c:abs(base_rank.index(c)-rank.index(c)) for c in CANDIDATES}; max_shift=max(max_shift,max(shifts.values()))
        results[name]={"ranking":rank,"scores":{r["candidate"]:r["proposed"]["opportunity_score"] for r in rows},"rank_shifts":shifts}
    return {"baseline_ranking":base_rank,"scenarios":results,"maximum_rank_shift":max_shift,"stability":"STABLE" if max_shift<=1 else "UNSTABLE","unstable_rule":"maximum rank movement >= 2 positions"}


def run_calibration(*, artifacts: dict[str, Any] | None=None, now: datetime | None=None) -> dict[str, Any]:
    artifacts=artifacts or load_artifacts(); v13=artifacts["v13"]; v14b1=artifacts["v14b1"]; v14b2=artifacts["v14b2"]
    analyses={a["niche"]:a for a in v13["analyses"] if a.get("niche") in CANDIDATES}
    if tuple(c for c in CANDIDATES if c in analyses)!=CANDIDATES: raise ValueError("All five fixed POC candidates must exist in the V1.3 artifact")
    rows=[calibrate_candidate(analyses[c],v14b1,v14b2) for c in CANDIDATES]
    current_rank=_ranking(rows,("current","opportunity_score")); proposed_rank=_ranking(rows,("proposed","opportunity_score"))
    return {"version":VERSION,"generated_at":(now or datetime.now(timezone.utc)).isoformat(),"mode":"OFFLINE_CALIBRATION_ONLY","would_production_scoring_change":"NO — audit-only","official_scores_changed":False,"provider_calls":0,"paid_calls":0,"DATAFORSEO_AMAZON_UAE_ENGLISH_COVERAGE":"NOT_CONFIRMED","DATAFORSEO_AMAZON_UAE_ARABIC_COVERAGE":"PARTIAL","provider_roles":PROVIDER_ROLES,"evidence_states":EVIDENCE_STATES,"coverage_aware_strategy":"Fixed 100-point denominator. Unavailable families contribute zero, their weights are not redistributed, and confidence falls with available weight.","current_opportunity_weights":CURRENT_OPPORTUNITY_WEIGHTS,"proposed_opportunity_weights":PROPOSED_OPPORTUNITY_WEIGHTS,"proposed_weight_rationale":"Audit-only consolidation emphasizes unchanged V1.3 economics (35%) while retaining demand (30%), competition attractiveness (25%), and risk attractiveness (10%).","demand_weights":DEMAND_WEIGHTS,"competition_weights":COMPETITION_WEIGHTS,"candidates":rows,"current_ranking":current_rank,"proposed_ranking":proposed_rank,"sensitivity":_sensitivity(rows,analyses,v14b1,v14b2)}


def render_report(bundle: dict[str, Any]) -> str:
    lines=["# V1.4C OPPORTUNITY SCORING CALIBRATION AND EVIDENCE FUSION","",f"Generated: {bundle['generated_at']}","Mode: OFFLINE / CALIBRATION ONLY","Would production scoring change? **NO — audit-only**","Provider calls: 0; paid calls: 0","","## Provider roles","",* [f"- {name}: **{value['role']}**" for name,value in bundle["provider_roles"].items()],"","English DataForSEO Amazon UAE coverage: NOT_CONFIRMED. Arabic coverage: PARTIAL. Arabic values never represent total UAE demand.","","## Weight audit","",f"Current weights: `{json.dumps(bundle['current_opportunity_weights'],sort_keys=True)}`",f"Proposed audit-only weights: `{json.dumps(bundle['proposed_opportunity_weights'],sort_keys=True)}`",bundle["proposed_weight_rationale"],"",f"Coverage arithmetic: {bundle['coverage_aware_strategy']}","","## Primary comparison","","| Candidate | Current demand | Proposed demand | Demand conf. | Current competition | Proposed competition | Competition conf. | Current opportunity | Proposed opportunity | Max landed @25% | Overall conf. |","|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in bundle["candidates"]:
        c,p=row["current"],row["proposed"]; landed="N/A" if row["max_landed_cost_25_aed"] is None else f"AED {row['max_landed_cost_25_aed']:.2f}"
        lines.append(f"| {row['candidate']} | {c['demand_score']:.2f} | {p['demand_score']:.2f} | {p['demand_confidence']:.2f} | {c['competition_score']:.2f} | {p['competition_score']:.2f} | {p['competition_confidence']:.2f} | {c['opportunity_score']:.2f} | {p['opportunity_score']:.2f} | {landed} | {p['overall_evidence_confidence']:.2f} |")
    lines += ["","Current ranking: "+" > ".join(bundle["current_ranking"]),"Proposed ranking: "+" > ".join(bundle["proposed_ranking"]),"", "## Candidate movement and arithmetic",""]
    for row in bundle["candidates"]:
        c,p=row["current"],row["proposed"]
        lines += [f"### {row['candidate']}","",f"Demand moved {c['demand_score']:.2f} → {p['demand_score']:.2f} because listing density, deduplicated review distribution, public search observations, and evidence breadth now contribute separately; Arabic evidence is capped at 10% of the search family.",f"Competition moved {c['competition_score']:.2f} → {p['competition_score']:.2f}; missing DataForSEO contributes zero rather than low-competition credit. Observed DataForSEO competition applies only to the crochet POC candidate.",f"Demand arithmetic: `{json.dumps(p['demand_arithmetic']['arithmetic'],ensure_ascii=False)}`",f"Competition arithmetic: `{json.dumps(p['competition_arithmetic']['arithmetic'],ensure_ascii=False)}`",f"Opportunity arithmetic: `{json.dumps(p['opportunity_arithmetic']['arithmetic'],ensure_ascii=False)}`",f"Economics: {row['economics_status']}; max landed cost at 25%: {row['max_landed_cost_25_aed'] if row['max_landed_cost_25_aed'] is not None else 'N/A'}.",""]
    s=bundle["sensitivity"]
    lines += ["## Sensitivity", "",f"Result: **{s['stability']}**; maximum rank shift: {s['maximum_rank_shift']}. Model is unstable when any tested scenario moves a candidate by two or more ranks."]
    for name,result in s["scenarios"].items(): lines.append(f"- {name}: {' > '.join(result['ranking'])}")
    lines += ["","Score and confidence remain separate. UNKNOWN, NOT_SUPPORTED, NOT_RUN, null, and stale evidence cannot add score. The companion JSON preserves every family score, evidence state, fact, weight, contribution, and unchanged economics snapshot."]
    return "\n".join(lines)+"\n"


def write_outputs(bundle: dict[str, Any], directory: str | Path="reports") -> tuple[Path,Path]:
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); base=directory/f"{stamp}-v1.4c-scoring-calibration"; md=Path(f"{base}.md"); js=Path(f"{base}.json"); md.write_text(render_report(bundle),encoding="utf-8"); js.write_text(json.dumps(bundle,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8"); return md,js


def main() -> int:
    bundle=run_calibration(); md,js=write_outputs(bundle); print(f"Report: {md}"); print(f"Evidence: {js}"); print("Provider calls: 0"); return 0
