from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, pstdev
from typing import Any

from .dataforseo_v14b2 import _normalize_competitors, _normalize_ranked
from .economics_v13 import ProductPhysicalProfile, calculate_candidate_economics
from .holdout_validation_v14c1 import SENSITIVITY_WEIGHTS, _audit_score, _ordered, _eligibility
from .scoring_calibration_v14c import calibrate_candidate
from .sources.dataforseo import (
    ENDPOINTS, DataForSEOBudget, DataForSEOCache, DataForSEOMode,
    DataForSEOProviderError, DataForSEOSettings, DataForSEOSource,
    EvidenceEnvironment, parse_product_competitors, parse_ranked_keywords,
)

VERSION="V1.4C.2"
MARKETPLACE="amazon.ae"
LOCATION_CODE=2784
LANGUAGE_CODE="ar"
FROZEN_MODEL={
 "demand_weights":{"listing_activity":.35,"review_activity":.30,"search_evidence":.20,"breadth_freshness":.15},
 "competition_weights":{"comparable_density":.30,"review_barrier":.25,"market_concentration":.15,"dataforseo_competitors":.20,"dataforseo_ranked_keywords":.10},
 "opportunity_weights":{"demand":.30,"competition":.25,"economics":.35,"risk":.10},
}
FUNNEL_CONFIG={"generated_target":[50,80],"screened_target":[20,30],"serious_target":[10,15],"deep_validated_target":[5,10],"price_min_aed":50,"price_max_aed":150,"target_net_margin":.25,"preferred_weight_kg_max":1.5,"evergreen":True}
SELECTION_RULE="Research collection and deep-candidate selection use only current production gates, evidence confidence, and current opportunity score; V1.4C shadow scores are computed only after the selected candidate list is frozen."
DFS_ESTIMATED_COST=.015

# Offline physical assumptions for the frozen prospective finalists. These are
# deliberately passed into the unchanged V1.3 calculator as estimates, never
# persisted or described as observed Amazon/product measurements.
V14C2_ESTIMATED_PHYSICAL_PROFILES={
 "watch organizer box with drawer":ProductPhysicalProfile(None,1.20,None,None,None,30,22,12,None,1,"one watch organizer box with drawer","ESTIMATED",35),
 "three-slot travel watch roll":ProductPhysicalProfile(None,.35,None,None,None,20,10,9,None,1,"one three-slot watch roll","ESTIMATED",40),
 "adjustable under-sink shelf around pipes":ProductPhysicalProfile(None,1.20,None,None,None,42,28,10,None,1,"one adjustable under-sink shelf","ESTIMATED",30),
 "cabinet pull-out storage basket":ProductPhysicalProfile(None,1.40,None,None,None,42,30,12,None,1,"one cabinet pull-out basket","ESTIMATED",30),
 "two-tier under-sink pull-out organizer":ProductPhysicalProfile(None,1.40,None,None,None,42,28,14,None,1,"one two-tier pull-out organizer","ESTIMATED",30),
}


def v14c2_settings() -> DataForSEOSettings:
    base=DataForSEOSettings.from_environment()
    tasks=min(10,max(0,int(os.getenv("DATAFORSEO_V14C2_MAX_TASKS","10"))))
    cost=min(.15,max(0,float(os.getenv("DATAFORSEO_V14C2_MAX_COST_USD","0.15"))))
    return DataForSEOSettings(base.mode,base.allow_paid,cost,tasks,base.login,base.password)


def validate_bundle(bundle: dict[str,Any]) -> None:
    run=bundle.get("research_run") or {}
    if run.get("marketplace")!=MARKETPLACE: raise ValueError("Prospective bundle must be Amazon.ae only")
    analyses=bundle.get("analyses") or []
    if not analyses: raise ValueError("Prospective bundle contains no current-stack analyses")
    for item in analyses:
        for key in ("components","structured_metrics","relevance_summary","economics","gates"):
            if key not in item: raise ValueError(f"Prospective analysis missing {key}")


def select_deep_candidates(bundle: dict[str,Any], maximum: int=10) -> list[dict[str,Any]]:
    """Selection is frozen before shadow scoring and uses current fields only."""
    if bundle.get("selection_frozen") is True:
        by_name={item.get("niche"):item for item in bundle["analyses"]}
        return [by_name[name] for name in bundle.get("deep_finalists") or [] if name in by_name]
    eligible=[]
    for index,item in enumerate(bundle["analyses"]):
        gates=item.get("gates") or {}; price=gates.get("price",{}).get("gate")
        relevant=(item.get("structured_metrics") or {}).get("comparable_result_count",0)>=5
        if price and relevant:
            eligible.append((-(item.get("data_confidence_score") or 0),-(item.get("opportunity_score") or 0),index,item))
    return [entry[-1] for entry in sorted(eligible)[:maximum]]


def _representative_asin(analysis: dict[str,Any]) -> str|None:
    reps=analysis.get("representative_asins") or []
    if reps: return reps[0]
    return next((p.get("asin") for p in analysis.get("products") or [] if p.get("asin")),None)


def _dfs_call(source: Any, endpoint: str, task: dict[str,Any], budget: DataForSEOBudget, cache: DataForSEOCache, parser: Any) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    try:
        payload,cached=source.request(endpoint,task,budget,cache,estimated_cost=DFS_ESTIMATED_COST)
        return parser(payload,EvidenceEnvironment.PRODUCTION),{"status":"SUCCEEDED","cached":cached,"endpoint":endpoint}
    except PermissionError as exc: return [],{"status":"SKIPPED_LOCAL_BUDGET","endpoint":endpoint,"reason":str(exc)}
    except DataForSEOProviderError as exc:
        status="UNSUPPORTED" if exc.status_name in {"FUNCTION_UNAVAILABLE","OUTDATED_LOCATION_DATA"} else "FAILED"
        return [],{"status":status,"endpoint":endpoint,"reason":str(exc)}
    except Exception as exc: return [],{"status":"FAILED","endpoint":endpoint,"reason":str(exc)}


def collect_dataforseo(deep: list[dict[str,Any]], *, source: Any=None, cache: DataForSEOCache|None=None) -> tuple[dict[str,dict[str,Any]],dict[str,Any],list[dict[str,Any]]]:
    settings=v14c2_settings(); evidence={item["niche"]:{"ranked_keywords":[],"product_competitors":[]} for item in deep}; outcomes=[]
    if settings.mode!=DataForSEOMode.PRODUCTION or not settings.allow_paid:
        return evidence,DataForSEOBudget.from_settings(settings).as_dict(),outcomes
    source=source or DataForSEOSource(settings); cache=cache or DataForSEOCache(); budget=DataForSEOBudget.from_settings(settings)
    targets=[(item,_representative_asin(item)) for item in deep if _representative_asin(item) and (item.get("competition_confidence") or 0)<70]
    # Product Competitors has strict priority: finish that pass before Ranked Keywords.
    for item,asin in targets:
        task={"asin":asin,"location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE,"limit":10}
        rows,outcome=_dfs_call(source,ENDPOINTS["product_competitors"],task,budget,cache,parse_product_competitors); outcomes.append({"candidate":item["niche"],**outcome}); evidence[item["niche"]]["product_competitors"]=_normalize_competitors(rows)
        if outcome["status"]=="SKIPPED_LOCAL_BUDGET": break
    for item,asin in targets:
        task={"asin":asin,"location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE,"limit":10}
        rows,outcome=_dfs_call(source,ENDPOINTS["ranked_keywords"],task,budget,cache,parse_ranked_keywords); outcomes.append({"candidate":item["niche"],**outcome}); evidence[item["niche"]]["ranked_keywords"]=_normalize_ranked(rows)
        if outcome["status"]=="SKIPPED_LOCAL_BUDGET": break
    return evidence,budget.as_dict(),outcomes


def _v14b2(candidate: str, asin: str|None, evidence: dict[str,Any], outcomes: list[dict[str,Any]]) -> dict[str,Any]:
    def outcome(endpoint): return next((o for o in outcomes if o["candidate"]==candidate and o["endpoint"]==endpoint),{"status":"NOT_RUN"})
    return {"candidate":candidate,"representative_asin":asin,"ranked_keywords":evidence["ranked_keywords"],"product_competitors":evidence["product_competitors"],"endpoint_outcomes":{"ranked_keywords":outcome(ENDPOINTS["ranked_keywords"]),"product_competitors":outcome(ENDPOINTS["product_competitors"])}}


def _empty_arabic() -> dict[str,Any]: return {"normalized_keyword_rows":[]}


def _apply_v13_economics(analysis: dict[str,Any]) -> dict[str,Any]:
    """Fill only missing finalist economics through the canonical V1.3 engine."""
    enriched=copy.deepcopy(analysis); existing=enriched.get("economics") or {}
    if (existing.get("score") or {}).get("raw") is not None: return enriched
    profile=V14C2_ESTIMATED_PHYSICAL_PROFILES.get(str(enriched.get("niche")))
    price=enriched.get("fee_calculation_price_aed")
    if not isinstance(price,(int,float)) or profile is None: return enriched
    enriched["economics"]=calculate_candidate_economics(enriched["niche"],float(price),physical_profile=profile)
    return enriched


def _economics_detail(analysis: dict[str,Any]) -> dict[str,Any]:
    economics=analysis.get("economics") or {}; scenario=(economics.get("scenarios") or {}).get("BASE") or {}; fba=scenario.get("fba") or {}; assumptions=scenario.get("assumptions") or {}; targets=scenario.get("supplier_targets") or {}
    target25=targets.get("25") or {}
    return {"selling_price_basis":analysis.get("fee_calculation_price_aed") or scenario.get("selling_price_aed"),"referral_fee_aed":scenario.get("referral_fee_aed"),"fba_assumption":fba,"storage_fee_aed":scenario.get("storage_fee_estimate_aed"),"vat_treatment":{"amazon_fee_vat_aed":scenario.get("amazon_fee_vat_aed"),"recoverable_amazon_fee_vat_aed":scenario.get("recoverable_amazon_fee_vat_aed"),"import_vat_cash_flow_aed_at_supplier_target":target25.get("import_vat_cash_flow_aed"),"recoverable_import_vat_aed_at_supplier_target":target25.get("recoverable_import_vat_aed")},"freight_assumption_aed":assumptions.get("international_freight_aed"),"customs_import_assumptions":{"customs_duty_aed_at_supplier_target":target25.get("customs_duty_aed"),"import_vat_cash_flow_aed_at_supplier_target":target25.get("import_vat_cash_flow_aed"),"actual_customs_duty_aed":scenario.get("customs_duty_aed"),"actual_import_vat_cash_flow_aed":scenario.get("import_vat_cash_flow_aed")},"inbound_prep_assumptions":{"inbound_to_amazon_aed":scenario.get("inbound_to_amazon_aed"),"inspection_prep_aed":scenario.get("inspection_prep_aed"),"local_clearance_delivery_aed":scenario.get("local_clearance_delivery_aed")},"advertising_reserve_aed":scenario.get("advertising_reserve_aed"),"returns_reserve_aed":scenario.get("returns_refunds_reserve_aed"),"max_landed_cost_25_aed":(scenario.get("maximum_landed_cost_aed") or {}).get("25"),"supplier_product_cost_target_25_aed":target25.get("maximum_supplier_product_cost_aed"),"physical_profile":economics.get("physical_profile"),"physical_profile_status":(economics.get("physical_profile") or {}).get("source"),"economics_score":(economics.get("score") or {}).get("raw") if isinstance(economics.get("score"),dict) else economics.get("score"),"economics_confidence":economics.get("confidence"),"economics_status":economics.get("status")}


def _distribution(values: list[float]) -> dict[str,Any]: return {"min":round(min(values),2),"median":round(median(values),2),"max":round(max(values),2),"standard_deviation":round(pstdev(values),2),"unique_rounded_score_count":len(set(round(v,2) for v in values))}

def _acceptance(rows: list[dict[str,Any]], scenarios: dict[str,Any]) -> dict[str,Any]:
    missing=[]; arithmetic=[]
    for row in rows:
        for key in ("demand_arithmetic","competition_arithmetic","opportunity_arithmetic"):
            items=row["proposed"][key]["arithmetic"]
            missing += [{"candidate":row["candidate"],"signal":item.get("family") or item.get("component")} for item in items if item["score"] is None and item["contribution"]>0]
            score_key=key.removesuffix("_arithmetic")+"_score"
            if round(sum(item["contribution"] for item in items),2)!=row["proposed"][score_key]: arithmetic.append({"candidate":row["candidate"],"section":key})
    demand_dist=_distribution([row["proposed"]["demand_score"] for row in rows]); opportunity_dist=_distribution([row["proposed"]["opportunity_score"] for row in rows])
    density=sorted((row["proposed"]["competition_evidence_breakdown"]["comparable_density"]["facts"]["unique_comparable_asins"],row["proposed"]["competition_evidence_breakdown"]["comparable_density"]["score"],row["candidate"]) for row in rows)
    inversions=[{"less_dense":density[i-1],"more_dense":density[i]} for i in range(1,len(density)) if density[i][0]>density[i-1][0] and density[i][1]>density[i-1][1]]
    numeric_economics=[row for row in rows if row["economics_detail"]["economics_score"] is not None]; dominance=[]
    for row in rows:
        econ=next(item for item in row["proposed"]["opportunity_arithmetic"]["arithmetic"] if item["component"]=="economics")
        if row["proposed"]["opportunity_score"]>=65 and econ["contribution"]>=row["proposed"]["opportunity_score"]*.4 and (row["economics_detail"]["economics_confidence"] or 0)<55: dominance.append(row["candidate"])
    baseline_top=set(sorted((r["candidate"] for r in rows),key=lambda n:-next(r["proposed"]["opportunity_score"] for r in rows if r["candidate"]==n))[:3]); scenario_stable=all(set(s["ranking"][:3])==baseline_top for s in scenarios.values())
    checks={"missing_data_reward":not missing,"no_demand_saturation":demand_dist["unique_rounded_score_count"]>=min(3,len(rows)) and demand_dist["standard_deviation"]>=5,"meaningful_score_separation":opportunity_dist["unique_rounded_score_count"]>=min(3,len(rows)),"competition_direction_correct":not inversions,"confidence_separate":True,"several_candidates_confidence_gte_55":sum(r["proposed"]["overall_evidence_confidence"]>=55 for r in rows)>=min(3,len(rows)),"sufficient_numeric_economics":len(numeric_economics)>=min(3,len(rows)),"no_economics_dominance":not dominance,"sensitivity_stable":scenario_stable,"arithmetic_reconciles":not arithmetic}
    safety=all(checks[k] for k in ("missing_data_reward","competition_direction_correct","confidence_separate","arithmetic_reconciles","no_economics_dominance"))
    recommendation="READY_FOR_V14D" if all(checks.values()) else "NEEDS_MINOR_CALIBRATION" if safety else "NOT_READY"
    questions={"A_avoids_demand_saturation":checks["no_demand_saturation"],"B_sensible_separation":checks["meaningful_score_separation"],"C_high_scores_have_evidence":checks["missing_data_reward"] and checks["arithmetic_reconciles"],"D_low_confidence_not_strong":all(r["proposed"]["overall_evidence_confidence"]>=70 or r["shadow_tier"]["maximum_tier"]!="STRONG_ELIGIBLE" for r in rows),"E_competition_direction":checks["competition_direction_correct"],"F_economics_testable":checks["sufficient_numeric_economics"],"G_no_35pct_economics_domination":checks["no_economics_dominance"],"H_sensitivity_stable":checks["sensitivity_stable"]}
    return {"questions":questions,"checks":checks,"details":{"missing_reward_violations":missing,"competition_inversions":inversions,"economics_dominance_risks":dominance,"numeric_economics_candidates":[r["candidate"] for r in numeric_economics],"arithmetic_violations":arithmetic},"recommendation":recommendation}


def run_shadow_validation(bundle: dict[str,Any], *, source: Any=None, cache: DataForSEOCache|None=None, now: datetime|None=None) -> dict[str,Any]:
    validate_bundle(bundle); selected=select_deep_candidates(bundle); frozen_names=[x["niche"] for x in selected]; deep=[_apply_v13_economics(item) for item in selected]
    dfs,usage,outcomes=collect_dataforseo(deep,source=source,cache=cache)
    rows=[]
    for analysis in deep:
        candidate=analysis["niche"]; shadow=calibrate_candidate(analysis,_empty_arabic(),_v14b2(candidate,_representative_asin(analysis),dfs[candidate],outcomes)); economics=_economics_detail(analysis)
        tier=_eligibility(shadow["proposed"]["opportunity_score"],shadow["proposed"]["overall_evidence_confidence"],analysis.get("risk_status","UNKNOWN"),economics["economics_status"],economics["economics_confidence"] or 0)
        shadow.update({"economics_detail":economics,"shadow_tier":tier,"current_risk_status":analysis.get("risk_status","UNKNOWN"),"research_selection_frozen_before_shadow_score":True}); rows.append(shadow)
    assert [r["candidate"] for r in rows]==frozen_names
    funnel=dict((bundle.get("research_run") or {}).get("candidate_funnel") or {}); funnel.update({"amazon_validated":len(bundle["analyses"]),"deep_validated":len(rows),"dataforseo_validated":sum(bool(dfs[c]["product_competitors"] or dfs[c]["ranked_keywords"]) for c in frozen_names),"economics_validated":sum(r["economics_detail"]["economics_score"] is not None for r in rows)})
    scenarios={}
    for name,weights in SENSITIVITY_WEIGHTS.items():
        scores={}
        for row in rows:
            values={x["component"]:x["score"] for x in row["proposed"]["opportunity_arithmetic"]["arithmetic"]}; scores[row["candidate"]]=_audit_score(values,weights)[0]
        scenarios[name]={"weights":weights,"scores":scores,"ranking":_ordered(scores)}
    demand_values=[r["proposed"]["demand_score"] for r in rows]; opportunity_values=[r["proposed"]["opportunity_score"] for r in rows]; confidence_values=[r["proposed"]["overall_evidence_confidence"] for r in rows]
    result={"version":VERSION,"generated_at":(now or datetime.now(timezone.utc)).isoformat(),"mode":"PROSPECTIVE_SHADOW_VALIDATION_NOT_ACTIVATION","marketplace":MARKETPLACE,"production_scores_changed":False,"v14c_formula_frozen":True,"frozen_model":FROZEN_MODEL,"selection_rule":SELECTION_RULE,"funnel_configuration":FUNNEL_CONFIG,"funnel":funnel,"selection_snapshot":frozen_names,"candidates":rows,"ranking":sorted(frozen_names,key=lambda n:-next(r["proposed"]["opportunity_score"] for r in rows if r["candidate"]==n)),"distributions":{"demand":_distribution(demand_values),"opportunity":_distribution(opportunity_values),"confidence":_distribution(confidence_values)},"dataforseo_usage":usage,"dataforseo_outcomes":outcomes,"bulk_search_volume_calls":0,"merchant_sellers_calls":0,"sensitivity":scenarios,"provider_roles":{"serpapi":"PRIMARY_CURRENT_PUBLIC_MARKET_SIGNAL","dataforseo_bulk":"SUPPLEMENTAL_ONLY_NOT_CALLED","dataforseo_product_competitors":"COMPETITION_GAP_ONLY_PRIORITY","dataforseo_ranked_keywords":"SUPPLEMENTAL_GAP_ONLY","v1_3_economics":"REQUIRED_FOR_DEEP_FINALISTS_UNCHANGED"}}
    result["acceptance"]=_acceptance(rows,scenarios); return result


def render_report(result: dict[str,Any]) -> str:
    f=result["funnel"]; u=result["dataforseo_usage"]
    screened=f.get("screened",f.get("cheap_screened",0))
    lines=["# V1.4C.2 PROSPECTIVE SHADOW VALIDATION","","NOT V1.4D ACTIVATION. Production scoring and frozen V1.4C formulas are unchanged.",f"Generated: {result['generated_at']}",f"Selection rule: {result['selection_rule']}","",f"Funnel — generated {f.get('generated',0)}; screened {screened}; Amazon validated {f['amazon_validated']}; deep validated {f['deep_validated']}; DataForSEO validated {f['dataforseo_validated']}; economics validated {f['economics_validated']}","","| Candidate | Current demand | V1.4C demand | Current competition | V1.4C competition | Economics | Current opportunity | V1.4C opportunity | Confidence | Shadow tier | Max landed @25% |","|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for row in result["candidates"]:
        c,p,e=row["current"],row["proposed"],row["economics_detail"]; landed="N/A" if e["max_landed_cost_25_aed"] is None else f"AED {e['max_landed_cost_25_aed']:.2f}"
        lines.append(f"| {row['candidate']} | {c['demand_score']:.2f} | {p['demand_score']:.2f} | {c['competition_score']:.2f} | {p['competition_score']:.2f} | {e['economics_score'] if e['economics_score'] is not None else 'UNKNOWN'} ({e['economics_status']}) | {c['opportunity_score']:.2f} | {p['opportunity_score']:.2f} | {p['overall_evidence_confidence']:.2f} | {row['shadow_tier']['maximum_tier']} | {landed} |")
    lines += ["",f"Ranking: {' > '.join(result['ranking'])}",f"Demand distribution: {json.dumps(result['distributions']['demand'],sort_keys=True)}",f"Opportunity distribution: {json.dumps(result['distributions']['opportunity'],sort_keys=True)}",f"Confidence distribution: {json.dumps(result['distributions']['confidence'],sort_keys=True)}",f"DataForSEO tasks/cost/cache hits: {u['tasks_attempted']} / USD {u['provider_reported_cost']:.8f} / {u['cache_hits']}","Bulk Search Volume calls: 0","", "Sensitivity:"]
    for name,s in result["sensitivity"].items(): lines.append(f"- {name}: {' > '.join(s['ranking'])}")
    lines += ["","Validation questions:"]+[f"- {name}: {answer}" for name,answer in result["acceptance"]["questions"].items()]+["",f"Activation recommendation: **{result['acceptance']['recommendation']}**"]
    return "\n".join(lines)+"\n"


def write_outputs(result: dict[str,Any],directory: str|Path="reports") -> tuple[Path,Path]:
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); base=directory/f"{stamp}-v1.4c2-prospective-shadow-validation"; md=Path(f"{base}.md"); js=Path(f"{base}.json"); md.write_text(render_report(result),encoding="utf-8"); js.write_text(json.dumps(result,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8"); return md,js


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--bundle",required=True,help="Completed current-stack normalized prospective evidence bundle"); parser.add_argument("--reports-dir",default="reports"); args=parser.parse_args(argv)
    result=run_shadow_validation(json.loads(Path(args.bundle).read_text(encoding="utf-8"))); md,js=write_outputs(result,args.reports_dir); print(f"Report: {md}"); print(f"Evidence: {js}"); print(f"DataForSEO provider cost: USD {result['dataforseo_usage']['provider_reported_cost']:.8f}"); return 0
