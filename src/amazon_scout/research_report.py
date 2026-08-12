from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .profitability import maximum_landed_cost
from .research_pipeline import canonical_funnel, evidence_cutoff, source_status_from_evidence, validate_funnel_invariants


def _fmt(value: Any) -> str:
    if value is None: return "UNKNOWN"
    if isinstance(value, float): return f"{value:.2f}"
    return str(value)


def _gate_table(item: dict[str, Any]) -> list[str]:
    lines = ["| Gate | Result | Reason |", "|---|---|---|"]
    for name in ("price", "demand", "competition", "risk", "confidence"):
        gate = item["gates"][name]
        lines.append(f"| {name.title()} | {'PASS' if gate['gate'] else 'FAIL'} | {gate['reason']} |")
    return lines


def _candidate_detail(item: dict[str, Any], rank: int | None = None) -> list[str]:
    heading = f"### {rank}. {item['niche']}" if rank is not None else f"### {item['niche']}"
    components = item["components"]; fee_basis = item["fee_calculation_price_aed"]; fee = item["known_fee_aed"]
    max_costs = {margin: maximum_landed_cost(fee_basis, fee, margin) if fee_basis and fee is not None else None for margin in (.20,.25,.30)}
    urls = list(dict.fromkeys(r.source_url for r in item["evidence"] if r.source_url))
    fresh=item.get("component_freshness",{}); metrics=item.get("structured_metrics",{})
    price_basis = "SCENARIO" if item['candidate_type'] != 'OBSERVED_MARKET_OPPORTUNITY' or (fee_basis is not None and fresh.get('price') != 'CURRENT') else "CURRENT OBSERVED AMAZON UAE PRICE"
    lines = [heading, "", f"- Candidate type: **{item['candidate_type']}**", f"- Representative ASINs: {', '.join(item.get('representative_asins',[])) or 'UNKNOWN'}", f"- SerpApi keyword: {', '.join(item.get('serpapi_keywords',[])) or 'UNKNOWN'}", f"- Relevant Amazon results sampled: {_fmt(metrics.get('relevant_result_count'))}", f"- Observed Amazon UAE price: AED {_fmt(item['observed_market_price_aed'])} (range {_fmt(item['observed_price_min_aed'])}–{_fmt(item['observed_price_max_aed'])})", f"- Observed price freshness: {fresh.get('price','UNKNOWN')}", f"- Current Amazon UAE price range/median: AED {_fmt(metrics.get('current_price_min_aed'))}–{_fmt(metrics.get('current_price_max_aed'))}; median AED {_fmt(metrics.get('current_price_median_aed'))}", f"- Proposed selling price: AED {_fmt(item['proposed_selling_price_aed'])}", f"- Scenario selling price: AED {_fmt(fee_basis) if price_basis == 'SCENARIO' else 'UNKNOWN'}", f"- Fee calculation price: AED {_fmt(fee_basis)}", f"- Selling-price basis: {price_basis}", f"- Rating sample / median: {_fmt(metrics.get('rating_sample_size'))} / {_fmt(metrics.get('median_rating'))}", f"- Review sample / median / P75: {_fmt(metrics.get('review_sample_size'))} / {_fmt(metrics.get('median_reviews'))} / {_fmt(metrics.get('p75_reviews'))}", f"- Sponsored count / density: {_fmt(metrics.get('sponsored_count'))} / {_fmt(metrics.get('sponsored_density'))}", f"- Unique brands / top-brand share: {_fmt(metrics.get('unique_brand_count'))} / {_fmt(metrics.get('top_brand_share'))}", f"- bought_last_month observations: {', '.join(map(str,metrics.get('bought_last_month_observations',[]))) or 'UNKNOWN'}", f"- Fee basis: AED {_fmt(fee_basis)}; known fees AED {_fmt(fee)}; known components: {', '.join(item['known_fee_components']) or 'none'}; unknown: {', '.join(item['unknown_fee_components'])}", f"- Demand: score {_fmt(components['demand']['score'])}, status {components['demand']['status']}, confidence {_fmt(components['demand']['confidence'])}%; freshness {fresh.get('demand','UNKNOWN')}", f"- Competition: score {_fmt(components['competition']['score'])}, status {components['competition']['status']}, confidence {_fmt(components['competition']['confidence'])}%; freshness {fresh.get('competition','UNKNOWN')}", f"- Risk: score {_fmt(components['risk']['score'])}, status {components['risk']['status']}, confidence {_fmt(components['risk']['confidence'])}%; freshness {fresh.get('risk','UNKNOWN')}", f"- Preliminary score: {_fmt(item['preliminary_opportunity_score'])}/100", f"- Validated opportunity score: {_fmt(item['validated_opportunity_score'])}/100", f"- Overall data confidence: {_fmt(item['data_confidence_score'])}%", f"- Recommendation tier: **{item['recommendation_tier']}**", f"- PRELIMINARY MAXIMUM LANDED COST before unknown FBA/other costs at 20% / 25% / 30%: AED {_fmt(max_costs[.20])} / {_fmt(max_costs[.25])} / {_fmt(max_costs[.30])}", f"- Remaining unknowns: {', '.join(item['remaining_unknowns']) or 'none identified'}", "", "#### Evidence gates", ""]
    lines.extend(_gate_table(item))
    lines += ["", f"- Why it passed or failed: {item['recommendation_tier']} follows the gate results above; missing evidence never receives neutral points.", f"- Evidence sources: {', '.join(urls[:8]) or 'UNKNOWN'}", "- What to verify next: research the first failed gate specifically, then re-ingest evidence and re-score.", ""]
    return lines


def render_research_report(raw: dict[str, Any], analyses: list[dict[str, Any]], source_status: dict[str, str] | None = None, *, generated_at: datetime | None = None) -> str:
    generated_at = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = [record for item in analyses for record in item["evidence"]]
    # Accepted evidence is authoritative for USED status; caller summaries cannot contradict it.
    statuses = source_status_from_evidence(records)
    if statuses["SerpApi"] != "USED" and raw.get("serpapi_usage", {}).get("configured"):
        statuses["SerpApi"] = "AVAILABLE_NOT_USED"
    funnel = canonical_funnel(raw["research_run"].get("candidate_funnel", {}), analyses); validate_funnel_invariants(funnel)
    raw["research_run"]["candidate_funnel"] = funnel
    cutoff = evidence_cutoff(records, generated_at)
    raw["research_run"]["evidence_cutoff"] = cutoff
    qualified = [a for a in analyses if a["recommendation_tier"] == "VALIDATED_CANDIDATE"]
    promising = [a for a in analyses if a["recommendation_tier"] == "PROMISING_BUT_UNVALIDATED"]
    bundles = [a for a in analyses if a["candidate_type"] in {"BUNDLE_HYPOTHESIS", "DIFFERENTIATION_HYPOTHESIS"}]
    gaps = [a for a in analyses if a["recommendation_tier"] == "EVIDENCE_GAP"]
    rejected = [a for a in analyses if a["recommendation_tier"] == "REJECTED_CONSTRAINT"]
    do_not = [a for a in analyses if a["recommendation_tier"] in {"HIGH_RISK", "DO_NOT_SOURCE"}]
    has_serpapi = any(r.source_provider == "serpapi" for r in records)
    lines = ["# AMAZON UAE PRODUCT OPPORTUNITY REPORT", "", f"Mode: {'RESEARCH + SERPAPI' if has_serpapi else 'RESEARCH'}", "Marketplace: Amazon.ae (`A2VIGQ35RCS4UG`)", "Currency: AED", f"Generated: {generated_at.isoformat().replace('+00:00','Z')}", f"Evidence cutoff: {cutoff}", "", "## DATA SOURCES", ""]
    for name in ("Codex live web search", "Amazon UAE official pages", "SerpApi", "DataForSEO", "Rainforest", "Amazon SP-API"):
        lines.append(f"- {name}: {statuses[name]}")
    usage=raw.get("serpapi_usage",{})
    lines += ["", "## SERPAPI USAGE", "", f"- Configured: {'yes' if usage.get('configured') else 'no'}", f"- Enabled: {'yes' if usage.get('enabled') else 'no'}", f"- Calls attempted: {usage.get('calls_attempted',0)}", f"- Calls succeeded: {usage.get('calls_succeeded',0)}", f"- Calls failed: {usage.get('calls_failed',0)}", f"- Calls saved by cache: {usage.get('calls_saved_by_cache',0)}", f"- Calls remaining from run budget: {usage.get('calls_remaining',usage.get('configured_max_calls',0))}", f"- Keywords searched: {', '.join(usage.get('keywords_queried',[])) or 'none'}", f"- Product detail calls: {usage.get('product_detail_calls',0)}", "- Budget scope: local run budget, not SerpApi account quota."]
    lines += ["", "## USER FILTERS", "", f"`{json.dumps(raw['research_run'].get('filters', {}), sort_keys=True)}`", "", "## CANONICAL CANDIDATE FUNNEL", ""]
    for key in ("generated", "screened", "web_evidence_backed", "serpapi_validated", "price_gate_passed", "demand_gate_passed", "competition_gate_passed", "risk_gate_passed", "validated", "bundle_hypotheses", "finalists"):
        lines.append(f"- {key.replace('_',' ').title()}: {funnel[key]}")
    lines += ["", f"## QUALIFIED FINALISTS — {len(qualified)}", ""]
    if not qualified: lines.append("No candidates met every required evidence gate and the 60% confidence threshold. Only 0 candidates qualified; weak candidates were not promoted to fill a Top 10.")
    for index, item in enumerate(qualified, 1): lines.extend(_candidate_detail(item, index))
    lines += ["", "## PROMISING BUT UNVALIDATED", ""]
    if not promising: lines.append("None.")
    for item in promising: lines.extend(_candidate_detail(item))
    lines += ["", "## BUNDLE / DIFFERENTIATION HYPOTHESES", ""]
    if not bundles: lines.append("None.")
    for item in bundles:
        lines += [f"### {item['niche']}", "", f"- Observed unit price: AED {_fmt(item['observed_market_price_aed'])}", f"- Observed pack configuration: {next((r.metric_unit for r in item['evidence'] if r.metric_name in {'current_price_aed','observed_market_price_aed'}), 'UNKNOWN')}", f"- Proposed bundle: {next((p.get('title') for p in item['products'] if p.get('title')), 'UNKNOWN')}", f"- Proposed selling price: AED {_fmt(item['proposed_selling_price_aed'])}", f"- Fee calculation price: AED {_fmt(item['fee_calculation_price_aed'])}", f"- Evidence supporting willingness-to-pay: {item['components']['demand']['observation_count']} current meaningful demand observations", f"- Evidence missing: {', '.join(item['remaining_unknowns']) or 'bundle-price validation'}", f"- Bundle confidence: {_fmt(item['data_confidence_score'])}%", "- Sourcing eligibility: NOT ELIGIBLE until the proposed bundle price has current market evidence.", ""]
        lines.extend(_gate_table(item)); lines.append("")
    lines += ["## EVIDENCE GAPS", ""]
    if not gaps: lines.append("None.")
    for item in gaps: lines.extend(_candidate_detail(item))
    lines += ["", "## REJECTED BY USER CONSTRAINTS", ""]
    if not rejected: lines.append("None.")
    for item in rejected: lines.extend(_candidate_detail(item))
    lines += ["", "## DO NOT SOURCE", ""]
    if not do_not: lines.append("No candidate has enough strong negative evidence for a definitive do-not-source classification; unresolved candidates remain validation targets only.")
    for item in do_not: lines.extend(_candidate_detail(item))
    source_targets = [a for a in qualified if a["top_3_to_source_eligible"]][:3]
    validate_targets = [a for a in analyses if not a["top_3_to_source_eligible"] and a["preliminary_opportunity_score"] is not None][:3]
    lines += ["", "## TOP 3 TO SOURCE", ""]
    if not source_targets: lines.append("None. Confidence and evidence gates prevent sourcing recommendations.")
    for item in source_targets: lines.append(f"- {item['niche']}")
    lines += ["", "## TOP 3 TO VALIDATE", ""]
    for item in validate_targets: lines.append(f"- {item['niche']} — research failed gates: {', '.join(name for name,g in item['gates'].items() if not g['gate'])}.")
    if raw.get("_quarantined_evidence"):
        lines += ["", "## QUARANTINED EVIDENCE", "", f"{len(raw['_quarantined_evidence'])} records were excluded for impossible future timestamps."]
    if raw.get("_validation_errors"):
        lines += ["", "## TIMESTAMP VALIDATION ERRORS", ""]
        lines.extend(f"- {item['field']}: {item['reason']}" for item in raw["_validation_errors"])
    return "\n".join(lines) + "\n"
