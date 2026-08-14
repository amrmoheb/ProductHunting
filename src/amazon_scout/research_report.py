from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .profitability import maximum_landed_cost
from .research_pipeline import LEGACY_CONSTRUCTION_WEIGHTS, canonical_funnel, evidence_cutoff, source_status_from_evidence, validate_funnel_invariants
from .scoring import synthetic_ceiling_audit
from .economics_v13 import required_economics_raw, score_with_economics


def _fmt(value: Any) -> str:
    if value is None: return "UNKNOWN"
    if isinstance(value, float): return f"{value:.2f}"
    return str(value)


def _sample_summary(values: list[float] | None) -> str:
    if not values: return "UNKNOWN"
    ordered=sorted(values); size=len(ordered); middle=ordered[size//2] if size%2 else (ordered[size//2-1]+ordered[size//2])/2
    return f"n={size}, range AED {ordered[0]:.2f}–{ordered[-1]:.2f}, median AED {middle:.2f}"


def _gate_table(item: dict[str, Any]) -> list[str]:
    lines = ["| Gate | Result | Reason |", "|---|---|---|"]
    for name in ("price", "demand", "competition", "risk", "confidence"):
        gate = item["gates"][name]
        lines.append(f"| {name.title()} | {'PASS' if gate['gate'] else 'FAIL'} | {gate['reason']} |")
    return lines


def _economics_section(analyses: list[dict[str, Any]]) -> list[str]:
    serious={"long handle baseboard cleaning tool","washable ceiling fan blade sleeve duster","adjustable airplane foot hammock","wood crochet blocking board"}
    items=[item for item in analyses if item["niche"] in serious]
    lines=["## ECONOMICS", "", "V1.4D consumes the unchanged V1.3 economics raw score at 35%. Scenario assumptions are estimates, not observed costs. UNKNOWN economics contributes zero with no weight redistribution. Amazon fee VAT is shown both as a modeled fee cost and separately as potentially recoverable VAT cash flow; import VAT is excluded from permanent landed cost and shown as cash flow only.", "", "Maximum landed cost formula: `selling price × (1 − target net margin) − Amazon fees − fee VAT − FBA − storage − advertising − returns − other operating reserves`.", ""]
    for item in items:
        econ=item.get("economics",{}); category=econ.get("category",{}); scenarios=econ.get("scenarios",{}); base=scenarios.get("BASE",{}); score=econ.get("score",{}); profile=econ.get("physical_profile") or {}; sens=econ.get("sensitivity",{})
        before=round(float(item.get("validated_opportunity_score") or item.get("preliminary_opportunity_score") or 0)-float(score.get("raw") or 0)*.20,2)
        targets=base.get("supplier_targets",{}); supplier_values=[v.get("maximum_supplier_product_cost_aed") for name in ("OPTIMISTIC","BASE","CONSERVATIVE") for v in [scenarios.get(name,{}).get("supplier_targets",{}).get("25",{})] if v.get("maximum_supplier_product_cost_aed") is not None]
        lines += [f"### {item['niche']}", "", f"- Score before economics / economics raw / contribution / new validated score: {_fmt(before)} / {_fmt(score.get('raw'))} / {_fmt((score.get('raw') or 0)*.20)} / {_fmt(item.get('validated_opportunity_score'))}", f"- Amazon UAE selling-price basis: AED {_fmt(base.get('selling_price_aed'))}; representative comparable ASIN: {_fmt(econ.get('representative_asin'))} at AED {_fmt(econ.get('representative_price_aed'))}", f"- Amazon fee category: {category.get('amazon_fee_category','UNKNOWN')} (confidence {_fmt(category.get('category_confidence'))}%); alternative scenarios: {', '.join(category.get('category_scenarios',[]))}; reason: {category.get('category_reason','UNKNOWN')}", f"- Referral fee: {_fmt((base.get('referral_fee_rate') or 0)*100)}% = AED {_fmt(base.get('referral_fee_aed'))} (minimum AED {_fmt(base.get('referral_fee_minimum_aed'))})", f"- FBA fulfillment: AED {_fmt(base.get('fba',{}).get('fee_aed'))}; tier {base.get('fba',{}).get('tier','UNKNOWN')}; status {base.get('fba',{}).get('status','UNKNOWN')}", f"- Amazon fee VAT / storage: AED {_fmt(base.get('amazon_fee_vat_aed'))} / AED {_fmt(base.get('storage_fee_estimate_aed'))}", f"- Advertising / returns assumptions: AED {_fmt(base.get('advertising_reserve_aed'))} ({_fmt(base.get('assumptions',{}).get('advertising_rate',0)*100)}%) / AED {_fmt(base.get('returns_refunds_reserve_aed'))} ({_fmt(base.get('assumptions',{}).get('returns_rate',0)*100)}%)", f"- Total Amazon/operating cost before product: AED {_fmt(base.get('total_amazon_operating_cost_before_product_aed'))}", f"- Maximum landed cost at 20% / 25% / 30%: AED {_fmt(base.get('maximum_landed_cost_aed',{}).get('20'))} / {_fmt(base.get('maximum_landed_cost_aed',{}).get('25'))} / {_fmt(base.get('maximum_landed_cost_aed',{}).get('30'))}", f"- Supplier target product cost at 25%: AED {_fmt(targets.get('25',{}).get('maximum_supplier_product_cost_aed'))}; scenario range AED {_fmt(min(supplier_values) if supplier_values else None)}–{_fmt(max(supplier_values) if supplier_values else None)}", f"- Break-even landing cost / selling price before product cost: AED {_fmt(base.get('break_even_landing_cost_aed'))} / AED {_fmt(base.get('break_even_selling_price_before_product_cost_aed'))}", f"- Physical profile: packaged {_fmt(profile.get('packaged_weight_kg'))} kg, {_fmt(profile.get('packaged_length_cm'))} × {_fmt(profile.get('packaged_width_cm'))} × {_fmt(profile.get('packaged_height_cm'))} cm; source {profile.get('source','UNKNOWN')}; confidence {_fmt(profile.get('confidence'))}%", f"- Economics status / confidence / sensitivity: {econ.get('status','UNKNOWN')} / {_fmt(econ.get('confidence'))}% / {sens.get('classification','UNKNOWN')}", f"- Required economics raw to reach 55 / 65 from pre-economics score: {_fmt(required_economics_raw(before,55))} / {_fmt(required_economics_raw(before,65))}; maximum score with economics raw 100: {_fmt(score_with_economics(before,100))}", f"- Remaining actual-cost unknowns: factory cost, verified freight quote, customs assessment, actual returns/ads, and observed packaged dimensions/weight. Actual landed cost and actual net margin remain UNKNOWN.", f"- Fee evidence: {', '.join(econ.get('evidence_sources',[]))}", "", "| Scenario | Ads | Returns | Storage months | Total pre-product cost | Max landed @25% | Supplier target @25% |", "|---|---:|---:|---:|---:|---:|---:|"]
        score_parts=score.get("components",{}); score_weights=score.get("weights",{}); score_contrib=score.get("contributions",{})
        lines[len(lines)-2:len(lines)-2] = ["- Economics-score arithmetic: "+"; ".join(f"{name} {_fmt(score_parts.get(name))} × {_fmt(score_weights.get(name))} = {_fmt(score_contrib.get(name))}" for name in ("actual_margin","landed_cost_headroom","fee_burden","conservative_robustness","evidence_confidence"))+f"; total {_fmt(score.get('raw'))}. Actual margin is zero until actual landed cost is known.", ""]
        for name in ("OPTIMISTIC","BASE","CONSERVATIVE"):
            s=scenarios.get(name,{}); a=s.get("assumptions",{})
            lines.append(f"| {name} | {_fmt(a.get('advertising_rate',0)*100)}% | {_fmt(a.get('returns_rate',0)*100)}% | {_fmt(a.get('storage_months'))} | AED {_fmt(s.get('total_amazon_operating_cost_before_product_aed'))} | AED {_fmt(s.get('maximum_landed_cost_aed',{}).get('25'))} | AED {_fmt(s.get('supplier_targets',{}).get('25',{}).get('maximum_supplier_product_cost_aed'))} |")
        material=[c for c in sens.get("cases",[]) if c.get("case") in {"PRICE_MINUS_10","PRICE_BASE","ADS_15","RETURNS_10"}]
        lines += ["", "Sensitivity (using the base 25%-margin maximum landed cost as the reference until a supplier quote exists): "+"; ".join(f"{c['case']}={_fmt(None if c.get('net_margin') is None else c['net_margin']*100)}% margin" for c in material), ""]
    first=next((i.get("economics",{}) for i in items),{})
    lines += ["### Fee-rule audit", "", f"- Fee-rule version: {first.get('fee_rule_version','UNKNOWN')}; effective date: {first.get('effective_date','UNKNOWN')}; retrieved: {first.get('retrieved_at','UNKNOWN')}.", "- The official pricing schedule displayed fees effective 1 August 2025. Expired promotional discounts were explicitly excluded.", "- FBA Revenue Calculator workflow: manual public/guest or Seller Central use for an existing ASIN, or `Define Product` for a hypothetical item. This release did not automate authenticated pages or invent calculator results.", ""]
    return lines


def _candidate_detail(item: dict[str, Any], rank: int | None = None) -> list[str]:
    heading = f"### {rank}. {item['niche']}" if rank is not None else f"### {item['niche']}"
    components = item["components"]; fee_basis = item["fee_calculation_price_aed"]; fee = item["known_fee_aed"]
    base_economics = item.get("economics",{}).get("scenarios",{}).get("BASE",{})
    canonical_max = base_economics.get("maximum_landed_cost_aed",{})
    max_costs = {margin: canonical_max.get(str(int(margin*100))) for margin in (.20,.25,.30)} if canonical_max else {margin: maximum_landed_cost(fee_basis, fee, margin) if fee_basis and fee is not None else None for margin in (.20,.25,.30)}
    canonical_fee = base_economics.get("total_amazon_operating_cost_before_product_aed")
    displayed_fee = canonical_fee if canonical_fee is not None else fee
    known_components = "referral, FBA fulfillment, storage, Amazon fee VAT, ads/returns reserves" if canonical_fee is not None else (', '.join(item['known_fee_components']) or 'none')
    urls = list(dict.fromkeys(r.source_url for r in item["evidence"] if r.source_url))
    fresh=item.get("component_freshness",{}); metrics=item.get("structured_metrics",{}); relevance=item.get("relevance_summary",{}); breakdown=item.get("score_breakdown") or {}
    price_basis = "SCENARIO" if item['candidate_type'] != 'OBSERVED_MARKET_OPPORTUNITY' or (fee_basis is not None and fresh.get('price') != 'CURRENT') else "CURRENT OBSERVED AMAZON UAE PRICE"
    lines = [heading, "", f"- Candidate type: **{item['candidate_type']}**", f"- Commercial classification: **{item.get('commercial_opportunity_classification','UNKNOWN')}**", f"- Representative comparable ASINs: {', '.join(item.get('representative_asins',[])) or 'UNKNOWN'}", f"- SerpApi keyword: {', '.join(item.get('serpapi_keywords',[])) or 'UNKNOWN'}", f"- Raw result rows / unique ASINs / duplicate rows removed from statistics: {_fmt(metrics.get('raw_result_rows'))} / {_fmt(metrics.get('unique_ASINs'))} / {_fmt(metrics.get('duplicate_ASIN_rows_removed_from_statistics'))}", f"- All relevant Amazon ASINs: {_fmt(metrics.get('relevant_result_count'))}; commercially comparable ASINs: {_fmt(metrics.get('comparable_result_count'))}", f"- All relevant product price range/median: AED {_fmt(metrics.get('current_price_min_aed'))}–{_fmt(metrics.get('current_price_max_aed'))}; median AED {_fmt(metrics.get('current_price_median_aed'))}", f"- Comparable segment price range/median: AED {_fmt(metrics.get('comparable_price_min_aed'))}–{_fmt(metrics.get('comparable_price_max_aed'))}; median AED {_fmt(metrics.get('comparable_price_median_aed'))}", f"- Comparable segment P25 / mean / P75: AED {_fmt(metrics.get('comparable_price_p25_aed'))} / {_fmt(metrics.get('comparable_price_mean_aed'))} / {_fmt(metrics.get('comparable_price_p75_aed'))}", f"- Comparable target-band count / ratio: {_fmt(metrics.get('comparable_in_target_band_count'))} / {_fmt(metrics.get('comparable_in_target_band_ratio'))}", f"- Observed Amazon UAE price across all relevant products: AED {_fmt(item['observed_market_price_aed'])} (range {_fmt(item['observed_price_min_aed'])}–{_fmt(item['observed_price_max_aed'])})", f"- Observed price freshness: {fresh.get('price','UNKNOWN')}", f"- Comparable price evidence freshness: {fresh.get('price','UNKNOWN')}", f"- Proposed selling price: AED {_fmt(item['proposed_selling_price_aed'])}", f"- Scenario selling price: AED {_fmt(fee_basis) if price_basis == 'SCENARIO' else 'UNKNOWN'}", f"- Fee calculation price: AED {_fmt(fee_basis)}", f"- Selling-price basis: {price_basis}", f"- Comparable rating sample / median: {_fmt(metrics.get('rating_sample_size'))} / {_fmt(metrics.get('median_rating'))}", f"- Comparable review sample / median / P75: {_fmt(metrics.get('review_sample_size'))} / {_fmt(metrics.get('median_reviews'))} / {_fmt(metrics.get('p75_reviews'))}", f"- Comparable sponsored count / density: {_fmt(metrics.get('sponsored_count'))} / {_fmt(metrics.get('sponsored_density'))}", f"- Comparable unique brands / top-brand share: {_fmt(metrics.get('unique_brand_count'))} / {_fmt(metrics.get('top_brand_share'))}", f"- bought_last_month observations: {', '.join(map(str,metrics.get('bought_last_month_observations',[]))) or 'UNKNOWN'}", f"- Fee basis: AED {_fmt(fee_basis)}; known fees AED {_fmt(fee)}; known components: {', '.join(item['known_fee_components']) or 'none'}; unknown: {', '.join(item['unknown_fee_components'])}", f"- Demand: score {_fmt(components['demand']['score'])}, status {components['demand']['status']}, confidence {_fmt(components['demand']['confidence'])}%; freshness {fresh.get('demand','UNKNOWN')}", f"- Competition (comparable segment): score {_fmt(components['competition']['score'])}, status {components['competition']['status']}, confidence {_fmt(components['competition']['confidence'])}%; freshness {fresh.get('competition','UNKNOWN')}", f"- Risk: score {_fmt(components['risk']['score'])}, status {components['risk']['status']}, confidence {_fmt(components['risk']['confidence'])}%; freshness {fresh.get('risk','UNKNOWN')}", f"- Preliminary score: {_fmt(item['preliminary_opportunity_score'])}/100", f"- Validated opportunity score: {_fmt(item['validated_opportunity_score'])}/100", f"- Overall data confidence: {_fmt(item['data_confidence_score'])}%", f"- Recommendation tier: **{item['recommendation_tier']}**", f"- PRELIMINARY MAXIMUM LANDED COST before unknown FBA/other costs at 20% / 25% / 30%: AED {_fmt(max_costs[.20])} / {_fmt(max_costs[.25])} / {_fmt(max_costs[.30])}", f"- Remaining unknowns: {', '.join(item['remaining_unknowns']) or 'none identified'}", "", "#### Score arithmetic", ""]
    for index, line in enumerate(lines):
        if line.startswith("- Fee basis:"):
            lines[index] = f"- Fee basis: AED {_fmt(fee_basis)}; canonical V1.3 Amazon/operating fees AED {_fmt(displayed_fee)}; known components: {known_components}; unknown: {', '.join(item['unknown_fee_components'])}"
    for name, component in breakdown.get("components",{}).items(): lines.append(f"- {name}: raw {_fmt(component['raw'])}; weight {_fmt(component['weight'])}; contribution {_fmt(component['contribution'])}; missing behavior {component['missing_evidence_behavior']}")
    lines += [f"- Confidence adjustment: multiplier {_fmt(breakdown.get('confidence_adjustment',{}).get('multiplier'))}; behavior {breakdown.get('confidence_adjustment',{}).get('behavior','UNKNOWN')}", f"- Penalties: {breakdown.get('penalties',[])}", f"- Final pre-confidence score: {_fmt(breakdown.get('final_pre_confidence_score'))}", f"- Final validated opportunity score: {_fmt(breakdown.get('final_validated_opportunity_score'))}", "", "#### Evidence gates", ""]
    lines[4:4] = [f"- SerpApi relevance: total {_fmt(relevance.get('total_serpapi_results'))}; target {_fmt(relevance.get('target_results'))}; exact {_fmt(relevance.get('exact_results'))}; close {_fmt(relevance.get('close_variants'))}; accessory-to-target excluded {_fmt(relevance.get('accessory_to_target_exclusions'))}; wrong products excluded {_fmt(relevance.get('excluded_wrong_products'))}; ambiguous {_fmt(relevance.get('ambiguous_results'))}", f"- Exact-target price sample: {_sample_summary(relevance.get('exact_target_price_sample'))}", f"- Close-variant price sample: {_sample_summary(relevance.get('close_variant_price_sample'))}", f"- Combined validated price sample: {_sample_summary(relevance.get('combined_validated_price_sample'))}", f"- Risk reasons: {'; '.join(components['risk'].get('risk_reasons',[])) or 'UNKNOWN'}", f"- Risk source URLs: {', '.join(components['risk'].get('risk_source_urls',[])) or 'UNKNOWN'}"]
    lines.extend(_gate_table(item))
    lines += ["", f"- Why it passed or failed: {item['recommendation_tier']} follows the gate results above; missing evidence never receives neutral points.", f"- Evidence sources: {', '.join(urls[:8]) or 'UNKNOWN'}", "- What to verify next: research the first failed gate specifically, then re-ingest evidence and re-score.", ""]
    return lines


def render_research_report(raw: dict[str, Any], analyses: list[dict[str, Any]], source_status: dict[str, str] | None = None, *, generated_at: datetime | None = None) -> str:
    generated_at = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    records = [record for item in analyses for record in item["evidence"]]
    # Accepted evidence is authoritative for USED status; caller summaries cannot contradict it.
    statuses = source_status_from_evidence(records, canonical_economics_used=bool(raw.get("v13_economics")))
    if statuses["SerpApi"] != "USED" and raw.get("serpapi_usage", {}).get("configured"):
        statuses["SerpApi"] = "AVAILABLE_NOT_USED"
    funnel = canonical_funnel(raw["research_run"].get("candidate_funnel", {}), analyses); validate_funnel_invariants(funnel)
    raw["research_run"]["candidate_funnel"] = funnel
    cutoff = evidence_cutoff(records, generated_at)
    raw["research_run"]["evidence_cutoff"] = cutoff
    technically_validated = [a for a in analyses if a.get("technically_validated")]
    qualified = [a for a in analyses if a.get("qualified_strong_opportunity")]
    promising = [a for a in analyses if a["recommendation_tier"] in {"PROMISING_BUT_UNVALIDATED", "VALIDATED"}]
    bundles = [a for a in analyses if a["candidate_type"] in {"BUNDLE_HYPOTHESIS", "DIFFERENTIATION_HYPOTHESIS"}]
    premium_hypotheses = [a for a in analyses if a["recommendation_tier"] == "PREMIUM_POSITIONING_HYPOTHESIS"]
    gaps = [a for a in analyses if a["recommendation_tier"] in {"EVIDENCE_GAP", "PRELIMINARY_NEEDS_EVIDENCE"}]
    rejected = [a for a in analyses if a["recommendation_tier"] == "REJECTED_CONSTRAINT"]
    do_not = [a for a in analyses if a["recommendation_tier"] in {"HIGH_RISK", "DO_NOT_SOURCE"}]
    has_serpapi = any(r.source_provider == "serpapi" for r in records)
    lines = ["# AMAZON UAE PRODUCT OPPORTUNITY REPORT", "", "Production scoring: **V1.4D**", f"Mode: {'RESEARCH + SERPAPI' if has_serpapi else 'RESEARCH'}", "Marketplace: Amazon.ae (`A2VIGQ35RCS4UG`)", "Currency: AED", f"Generated: {generated_at.isoformat().replace('+00:00','Z')}", f"Evidence cutoff: {cutoff}", "", "## DATA SOURCES", ""]
    for name in ("Codex live web search", "Amazon UAE official pages", "SerpApi", "DataForSEO", "Rainforest", "Amazon SP-API"):
        lines.append(f"- {name}: {statuses[name]}")
    usage=raw.get("serpapi_usage",{})
    lines += ["", "## SERPAPI USAGE", "", f"- Configured: {'yes' if usage.get('configured') else 'no'}", f"- Enabled: {'yes' if usage.get('enabled') else 'no'}", f"- Calls attempted: {usage.get('calls_attempted',0)}", f"- Calls succeeded: {usage.get('calls_succeeded',0)}", f"- Calls failed: {usage.get('calls_failed',0)}", f"- Calls saved by cache: {usage.get('calls_saved_by_cache',0)}", f"- Calls remaining from run budget: {usage.get('calls_remaining',usage.get('configured_max_calls',0))}", f"- Keywords searched: {', '.join(usage.get('keywords_queried',[])) or 'none'}", f"- Product detail calls: {usage.get('product_detail_calls',0)}", "- Budget scope: local run budget, not SerpApi account quota."]
    lines += ["", "## USER FILTERS", "", f"`{json.dumps(raw['research_run'].get('filters', {}), sort_keys=True)}`", "", "## CANONICAL CANDIDATE FUNNEL", ""]
    for key in ("generated", "screened", "web_evidence_backed", "serpapi_validated", "price_gate_passed", "demand_gate_passed", "competition_gate_passed", "risk_gate_passed", "technically_validated", "strong_opportunities", "bundle_hypotheses", "finalists"):
        lines.append(f"- {key.replace('_',' ').title()}: {funnel[key]}")
    lines += ["", f"## TECHNICALLY VALIDATED — {len(technically_validated)}", ""]
    if not technically_validated: lines.append("No candidates passed price, demand, competition, risk, and the V1.4D 55% VALIDATED confidence gate.")
    for index, item in enumerate(technically_validated, 1): lines.extend(_candidate_detail(item, index))
    lines += ["", f"## QUALIFIED STRONG OPPORTUNITIES — {len(qualified)}", ""]
    if not qualified: lines.append("No technically validated candidate reached the configured validated opportunity score threshold of 65. Technically validated weak candidates did not fail their evidence gates; their deterministic opportunity scores were simply below the recommendation threshold. Under the former combined label this was `QUALIFIED FINALISTS — 0`; weak candidates were not promoted merely to fill a requested count.")
    for index, item in enumerate(qualified, 1): lines.extend(_candidate_detail(item, index))
    lines += ["", "## PROMISING BUT UNVALIDATED", ""]
    if not promising: lines.append("None.")
    for item in promising: lines.extend(_candidate_detail(item))
    lines += ["", "## BUNDLE / DIFFERENTIATION HYPOTHESES", ""]
    if not bundles: lines.append("None.")
    for item in bundles:
        lines += [f"### {item['niche']}", "", f"- Observed unit price: AED {_fmt(item['observed_market_price_aed'])}", f"- Observed pack configuration: {next((r.metric_unit for r in item['evidence'] if r.metric_name in {'current_price_aed','observed_market_price_aed'}), 'UNKNOWN')}", f"- Proposed bundle: {next((p.get('title') for p in item['products'] if p.get('title')), 'UNKNOWN')}", f"- Proposed selling price: AED {_fmt(item['proposed_selling_price_aed'])}", f"- Fee calculation price: AED {_fmt(item['fee_calculation_price_aed'])}", f"- Evidence supporting willingness-to-pay: {item['components']['demand']['observation_count']} current meaningful demand observations", f"- Evidence missing: {', '.join(item['remaining_unknowns']) or 'bundle-price validation'}", f"- Bundle confidence: {_fmt(item['data_confidence_score'])}%", "- Sourcing eligibility: NOT ELIGIBLE until the proposed bundle price has current market evidence.", ""]
        lines.extend(_gate_table(item)); lines.append("")
    lines += ["## PREMIUM POSITIONING HYPOTHESES", ""]
    if not premium_hypotheses: lines.append("None.")
    for item in premium_hypotheses:
        metrics=item.get("structured_metrics",{})
        lines += [f"- **{item['niche']}** — the normal comparable segment did not pass the price gate; premium/adjacent listings exist in-band, but willingness-to-pay for the target positioning is not validated (comparable median AED {_fmt(metrics.get('comparable_price_median_aed'))}, in-band ratio {_fmt(metrics.get('comparable_in_target_band_ratio'))})."]
    lines.append("")
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
    validate_targets = [a for a in analyses if not a.get("technically_validated") and a["preliminary_opportunity_score"] is not None][:3]
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
    plan=raw.get("risk_gap_research_plan",{})
    if plan.get("triggered"):
        lines += ["", "## AUTOMATIC ZERO-PAID RISK-GAP RESEARCH", "", f"Candidates: {', '.join(x['niche'] for x in plan['candidates'])}", "SerpApi calls allowed/used: 0. Codex must research the listed authoritative UAE sources, ingest explicit risk evidence, and re-run scoring before treating the report as final."]
    if raw.get("v124_audit"):
        audit=raw["v124_audit"]; baseline=(audit.get("baseline_report") or {}).get("analyses",[]); before={item["niche"]:item for item in baseline}; after={item["niche"]:item for item in analyses}
        affected=["foldable aluminum laptop riser","heavy duty beach towel clips","luggage handle cup sling","padded cable machine ankle straps","stackable mesh sweater drying rack"]
        lines += ["", "## V1.2.4 TARGET-AWARE RELEVANCE BEFORE / AFTER", "", "| Niche | Phase | Total | Target | Close | Accessory-to-target | Wrong | Comparable ASINs | Median AED | Price | Demand | Competition | Confidence | Score |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|"]
        for niche in affected:
            for phase,item in (("Before",before.get(niche)),("After",after.get(niche))):
                if not item: continue
                rel=item.get("relevance_summary",{}); metrics=item.get("structured_metrics",{}); gates=item.get("gates",{})
                lines.append(f"| {niche} | {phase} | {_fmt(rel.get('total_serpapi_results'))} | {_fmt(rel.get('target_results',rel.get('exact_results',0)+rel.get('close_variants',0)))} | {_fmt(rel.get('close_variants'))} | {_fmt(rel.get('accessory_to_target_exclusions',rel.get('excluded_accessories')))} | {_fmt(rel.get('excluded_wrong_products'))} | {_fmt(metrics.get('comparable_result_count'))} | {_fmt(metrics.get('comparable_price_median_aed'))} | {'PASS' if gates.get('price',{}).get('gate') else 'FAIL'} | {'PASS' if gates.get('demand',{}).get('gate') else 'FAIL'} | {'PASS' if gates.get('competition',{}).get('gate') else 'FAIL'} | {_fmt(item.get('data_confidence_score'))} | {_fmt(item.get('validated_opportunity_score'))} |")
        lines += ["", "## V1.2.4 UNIQUE-ASIN STATISTICAL AUDIT", "", "| Niche | Raw result rows | Unique ASINs | Duplicate rows removed |", "|---|---:|---:|---:|"]
        for item in analyses:
            metrics=item.get("structured_metrics",{}); lines.append(f"| {item['niche']} | {_fmt(metrics.get('raw_result_rows'))} | {_fmt(metrics.get('unique_ASINs'))} | {_fmt(metrics.get('duplicate_ASIN_rows_removed_from_statistics'))} |")
        lines += ["", "## V1.2.4 SCORE EXPLAINABILITY AUDIT", "", "Missing numeric components are treated as zero. Confidence is a separate gate with multiplier 1.0; it does not alter the arithmetic score. No additional score penalties are applied.", "", "| Niche | Price | Demand | Competition | Margin/economics | Risk | Differentiation | Pre-confidence | Validated | Confidence |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        keys=("price_attractiveness","demand","competition_attractiveness","margin_potential","risk_attractiveness","differentiation_potential")
        for item in analyses:
            breakdown=item.get("legacy_score_breakdown") or {}; components=breakdown.get("components",{}); contributions=[f"{_fmt(components.get(key,{}).get('raw'))} × {_fmt(components.get(key,{}).get('weight'))} = {_fmt(components.get(key,{}).get('contribution'))}" for key in keys]
            lines.append(f"| {item['niche']} | {' | '.join(contributions)} | {_fmt(breakdown.get('final_pre_confidence_score'))} | {_fmt(item.get('validated_opportunity_score'))} | {_fmt(item.get('data_confidence_score'))} |")
        lines += ["", "## V1.2.4 CURRENT TOP-CANDIDATE THRESHOLD AUDIT", ""]
        audited={"long handle baseboard cleaning tool","washable ceiling fan blade sleeve duster","adjustable airplane foot hammock","wood crochet blocking board"}
        for item in analyses:
            if item["niche"] not in audited: continue
            breakdown=item.get("legacy_score_breakdown") or {}; score=float(breakdown.get("final_pre_confidence_score") or 0); components=breakdown.get("components",{})
            losses=[]
            for name,component in components.items():
                ceiling=100*float(component["weight"]); loss=round(ceiling-float(component["contribution"]),3)
                if loss>0: losses.append(f"{name} loses {loss:.3f} points versus its component ceiling (raw {_fmt(component['raw'])}, contribution {_fmt(component['contribution'])}/{ceiling:.2f})")
            lines += [f"### {item['niche']}", "", f"- Score arithmetic: **{_fmt(score)}**; shortfall to 55: **{max(0,55-score):.2f}**; shortfall to 65: **{max(0,65-score):.2f}**.", f"- Specific suppressors: {'; '.join(losses)}.", "- Confidence multiplier: 1.0; confidence is a separate gate and does not explain the score shortfall.", ""]
        ceiling=synthetic_ceiling_audit(LEGACY_CONSTRUCTION_WEIGHTS); perfect=ceiling["PERFECT_CANDIDATE"]; very_good=ceiling["VERY_GOOD_CANDIDATE"]
        lines += ["", "## V1.2.4 PERFECT-CANDIDATE CEILING AUDIT", "", f"- PERFECT_CANDIDATE maximum validated opportunity score: **{_fmt(perfect['final_pre_confidence_score'])}** at 100% confidence.", f"- VERY_GOOD_CANDIDATE score: **{_fmt(very_good['final_pre_confidence_score'])}** at 85% confidence.", f"- Threshold 65 mathematically reachable: **{'YES' if perfect['final_pre_confidence_score'] >= 65 else 'NO — AUDIT FAILURE'}**.", "- UNKNOWN economics behavior: margin_potential is `None`, converted to effective raw 0, contributing 0 of the available 20 points. It is not a separate gate and does not change the confidence calculation; the score ceiling with all other components perfect becomes 80.", "- Regulatory guidance freshness: authoritative official-government regulatory evidence is `STATIC_GUIDANCE`, not artificially `CURRENT`; cited evidence still supports the risk gate."]
        old_funnel=audit.get("before_funnel") or {}; lines += ["", "## V1.2.4 CANONICAL FUNNEL BEFORE / AFTER", "", "| Metric | Before | After |", "|---|---:|---:|"]
        for key in ("generated","screened","serpapi_validated","price_gate_passed","demand_gate_passed","competition_gate_passed","risk_gate_passed","technically_validated","strong_opportunities"):
            lines.append(f"| {key} | {_fmt(old_funnel.get(key))} | {_fmt(funnel.get(key))} |")
        near=sum(item.get("validated_opportunity_score") is not None and 55 <= item["validated_opportunity_score"] < 65 for item in analyses); strong=sum(item.get("validated_opportunity_score") is not None and item["validated_opportunity_score"] >= 65 for item in analyses)
        lines += [f"| near_misses_55_64_99 | UNKNOWN | {near} |", f"| strong_ge_65 | {old_funnel.get('strong_opportunities',0)} | {strong} |", "", "Additional SerpApi calls consumed by V1.2.4 reprocessing: **0**."]
    if raw.get("v13_economics"):
        lines += [""] + _economics_section(analyses)
    return "\n".join(lines) + "\n"
