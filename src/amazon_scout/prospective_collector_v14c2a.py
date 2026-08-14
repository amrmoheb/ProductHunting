from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .evidence import load_bundle
from .research_pipeline import analyze_evidence_bundle, canonical_products_by_asin
from .serpapi_research import run as run_serpapi_validation

VERSION="V1.4C.2A"
MARKETPLACE="amazon.ae"
FUNNEL_TARGETS={"generated":[50,80],"cheap_screen_survivors":[20,30],"serious_amazon_validated":[10,15],"deep_validation_finalists":[5,10]}
BUSINESS_FILTERS={"price_min_aed":50,"price_max_aed":150,"target_net_margin":.25,"preferred_weight_kg_max":1.5,"evergreen":True,"exclude_electronics_batteries":True,"exclude_cosmetics":True,"exclude_supplements":True,"exclude_food_medicine":True,"exclude_fragile_oversized":True}
REJECTION_CODES={"REJECT_PRICE","REJECT_RESTRICTED_CATEGORY","REJECT_RISK","REJECT_RELEVANCE","REJECT_OVERSIZE","REJECT_INSUFFICIENT_EVIDENCE","REJECT_DUPLICATE"}
RESTRICTED={"electronics","battery","batteries","cosmetics","supplement","supplements","food","medicine","medical device","hazardous","adult"}
DATAFORSEO_CALLS={"bulk_search_volume":0,"ranked_keywords":0,"product_competitors":0,"merchant_sellers":0,"total":0}


def _semantic_key(name: str) -> str:
    tokens=[token.rstrip("s") for token in "".join(ch.lower() if ch.isalnum() else " " for ch in name).split()]
    return " ".join(sorted(dict.fromkeys(tokens)))


def validate_discovery_manifest(manifest: dict[str,Any]) -> None:
    if manifest.get("marketplace")!=MARKETPLACE: raise ValueError("Discovery manifest must target amazon.ae")
    if not isinstance(manifest.get("candidates"),list): raise ValueError("Discovery manifest requires candidates")
    for item in manifest["candidates"]:
        required=("candidate_id","candidate_name","query_source","discovered_at","marketplace","generation_reason")
        if any(not item.get(key) for key in required): raise ValueError("Every discovered candidate requires identity, source, timestamp, marketplace, and generation reason")
        if item["marketplace"]!=MARKETPLACE: raise ValueError("Non-UAE candidate rejected")


def deduplicate_candidates(candidates: list[dict[str,Any]]) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    kept=[]; rejected=[]; seen={}
    for item in candidates:
        key=_semantic_key(item["candidate_name"])
        if key in seen: rejected.append({"candidate_id":item["candidate_id"],"candidate_name":item["candidate_name"],"stage":"DISCOVERY_DEDUP","status":"REJECTED","reason_code":"REJECT_DUPLICATE","reason":f"Semantic duplicate of {seen[key]}"})
        else: seen[key]=item["candidate_id"]; kept.append(item)
    return kept,rejected


def cheap_screen(candidate: dict[str,Any]) -> tuple[bool,str|None,str]:
    category=str(candidate.get("category") or "").lower(); name=candidate["candidate_name"].lower()
    if any(term in category or term in name for term in RESTRICTED): return False,"REJECT_RESTRICTED_CATEGORY","Existing excluded/high-compliance category"
    if candidate.get("fragile") is True: return False,"REJECT_RISK","Explicitly fragile product"
    if candidate.get("oversized") is True or (isinstance(candidate.get("estimated_weight_kg"),(int,float)) and candidate["estimated_weight_kg"]>1.5): return False,"REJECT_OVERSIZE","Explicit oversized/heavy screen signal"
    price=candidate.get("observed_or_estimated_price_aed")
    if isinstance(price,(int,float)) and not 50<=price<=150: return False,"REJECT_PRICE","Explicit discovery price outside AED 50–150"
    if candidate.get("is_accessory_mismatch") is True or candidate.get("is_irrelevant") is True: return False,"REJECT_RELEVANCE","Explicit product/accessory mismatch"
    if not candidate.get("amazon_keyword"): return False,"REJECT_INSUFFICIENT_EVIDENCE","No Amazon UAE validation keyword"
    return True,None,"Passed deterministic cheap screen"


def screen_candidates(candidates: list[dict[str,Any]]) -> tuple[list[dict[str,Any]],list[dict[str,Any]],list[dict[str,Any]]]:
    survivors=[]; transitions=[]; rejections=[]
    for item in candidates:
        accepted,code,reason=cheap_screen(item); transition={"candidate_id":item["candidate_id"],"candidate_name":item["candidate_name"],"stage":"STAGE_A_CHEAP_SCREEN","status":"SURVIVED" if accepted else "REJECTED","reason_code":code,"reason":reason}; transitions.append(transition)
        (survivors if accepted else rejections).append(item if accepted else transition)
    return survivors,transitions,rejections


def _research_queries(candidates: list[dict[str,Any]]) -> list[tuple[str,str]]:
    """Adapt discovery candidates to the existing SerpApi research runner input."""
    return [(item["candidate_name"],item["amazon_keyword"]) for item in candidates]


def _insufficient_evidence_rejections(candidates: list[dict[str,Any]], raw: dict[str,Any]) -> list[dict[str,Any]]:
    evidenced={str(item.get("niche")) for item in raw.get("evidence",[]) if item.get("niche")}
    evidenced.update(str(item.get("niche")) for item in raw.get("products",[]) if item.get("niche"))
    return [{"candidate_id":item["candidate_id"],"candidate_name":item["candidate_name"],"stage":"STAGE_B_AMAZON_VALIDATION","status":"REJECTED","reason_code":"REJECT_INSUFFICIENT_EVIDENCE","reason":"Amazon UAE validation returned zero evidence for this candidate"} for item in candidates if item["candidate_name"] not in evidenced]


def _default_amazon_validator(survivors: list[dict[str,Any]], manifest: dict[str,Any], workdir: Path) -> dict[str,Any]:
    serious=survivors[:15]
    base={"research_run":{"id":f"v14c2a-{datetime.now(timezone.utc):%Y%m%d%H%M%S}","slug":"v1.4c2-prospective","marketplace":MARKETPLACE,"started_at":manifest.get("generated_at") or datetime.now(timezone.utc).isoformat(),"evidence_cutoff":datetime.now(timezone.utc).isoformat(),"filters":BUSINESS_FILTERS,"candidate_funnel":{"generated":len(manifest["candidates"]),"screened":len(survivors)}},"keywords":[],"products":manifest.get("products",[]),"evidence":manifest.get("evidence",[]),"source_summary":manifest.get("source_summary",{}),"provider_errors":[]}
    base_path=workdir/"discovery-base.json"; base_path.write_text(json.dumps(base),encoding="utf-8"); raw_path=workdir/"serpapi-validation.json"
    run_serpapi_validation(_research_queries(serious),output=raw_path,max_calls=15,base_bundle=base_path)
    raw=json.loads(raw_path.read_text(encoding="utf-8")); rejections=_insufficient_evidence_rejections(serious,raw)
    if not raw.get("evidence"):
        return {"raw":raw,"analyses":[],"amazon_rejections":rejections}
    validated_raw,records=load_bundle(raw_path); analyses=analyze_evidence_bundle(validated_raw,records)
    return {"raw":validated_raw,"analyses":analyses,"amazon_rejections":rejections}


def _production_shortlist(analyses: list[dict[str,Any]]) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    transitions=[]; eligible=[]
    for index,item in enumerate(analyses):
        gates=item["gates"]; justified=bool(gates["price"]["gate"] and gates["demand"]["gate"] and gates["competition"]["gate"] and item.get("opportunity_score") is not None)
        transitions.append({"candidate_name":item["niche"],"stage":"CURRENT_PRODUCTION_SHORTLIST","status":"ELIGIBLE" if justified else "REJECTED","reason_code":None if justified else "REJECT_INSUFFICIENT_EVIDENCE","reason":"Current production price, demand, and competition gates passed" if justified else "Current production gates/evidence did not justify deep validation"})
        if justified: eligible.append((-(item.get("data_confidence_score") or 0),-(item.get("opportunity_score") or 0),index,item))
    return [entry[-1] for entry in sorted(eligible)[:10]],transitions


def _economics_coverage(item: dict[str,Any]) -> dict[str,Any]:
    economics=item.get("economics") or {}; scenario=(economics.get("scenarios") or {}).get("BASE") or {}; targets=scenario.get("supplier_targets") or {}
    return {"price_basis":item.get("fee_calculation_price_aed"),"referral_fee_aed":scenario.get("referral_fee_aed"),"fulfilment_fba":scenario.get("fba"),"storage_fee_aed":scenario.get("storage_fee_estimate_aed"),"vat":{"amazon_fee_vat_aed":scenario.get("amazon_fee_vat_aed"),"import_vat_cash_flow_aed":scenario.get("import_vat_cash_flow_aed")},"ads_aed":scenario.get("advertising_reserve_aed"),"returns_aed":scenario.get("returns_refunds_reserve_aed"),"inbound_prep_aed":sum(x or 0 for x in (scenario.get("inbound_to_amazon_aed"),scenario.get("inspection_prep_aed"))) if scenario else None,"freight_assumption_aed":(scenario.get("assumptions") or {}).get("international_freight_aed"),"customs_duty_aed":scenario.get("customs_duty_aed"),"physical_profile":economics.get("physical_profile"),"max_landed_cost_25_aed":(scenario.get("maximum_landed_cost_aed") or {}).get("25"),"supplier_product_target_25_aed":(targets.get("25") or {}).get("maximum_supplier_product_cost_aed"),"economics_score":(economics.get("score") or {}).get("raw") if isinstance(economics.get("score"),dict) else economics.get("score"),"economics_confidence":economics.get("confidence"),"economics_status":economics.get("status")}


def collect(manifest: dict[str,Any], *, amazon_validator: Callable[[list[dict[str,Any]],dict[str,Any],Path],dict[str,Any]]|None=None, now: datetime|None=None) -> dict[str,Any]:
    validate_discovery_manifest(manifest); now=now or datetime.now(timezone.utc); unique,dedupe_rejections=deduplicate_candidates(manifest["candidates"]); survivors,screen_transitions,screen_rejections=screen_candidates(unique)
    with tempfile.TemporaryDirectory(prefix="v14c2a-") as temp:
        validation=(amazon_validator or _default_amazon_validator)(survivors,manifest,Path(temp))
    analyses=validation["analyses"]; amazon_rejections=validation.get("amazon_rejections",[]); deep,selection_transitions=_production_shortlist(analyses); deep_names={x["niche"] for x in deep}
    raw=validation.get("raw",{}); products_by_name={name:canonical_products_by_asin([p for p in raw.get("products",[]) if p.get("niche")==name])[0] for name in {a["niche"] for a in analyses}}
    serious=[]
    for item in analyses:
        snapshot={**item,"products":products_by_name.get(item["niche"],[]),"economics_coverage":_economics_coverage(item),"deep_finalist":item["niche"] in deep_names}
        serious.append(snapshot)
    usage=raw.get("serpapi_usage",{}); generated=len(manifest["candidates"]); funnel={"generated":generated,"deduplicated":len(unique),"cheap_screened":len(survivors),"amazon_validated":len(analyses),"deep_validated":len(deep),"economics_validated":sum(_economics_coverage(x)["economics_score"] is not None for x in deep)}
    if not (generated>=len(unique)>=len(survivors)>=len(analyses)>=len(deep)): raise ValueError("Prospective funnel invariant violated")
    return {"metadata":{"version":VERSION,"marketplace":MARKETPLACE,"generated_at":now.isoformat(),"selection_frozen":True,"selection_frozen_at":now.isoformat(),"selection_model":"CURRENT_PRODUCTION","shadow_model_used_for_selection":False,"collector_network_policy":"SERPAPI_PUBLIC_AMAZON_ONLY; DATAFORSEO_FORBIDDEN"},"research_run":{"id":f"v14c2a-{now:%Y%m%d%H%M%S}","slug":"v1.4c2-prospective-evidence-bundle","marketplace":MARKETPLACE,"started_at":manifest.get("generated_at") or now.isoformat(),"evidence_cutoff":now.isoformat(),"filters":BUSINESS_FILTERS,"candidate_funnel":funnel},"funnel_targets_not_quotas":FUNNEL_TARGETS,"funnel":funnel,"generated_candidates":manifest["candidates"],"stage_transitions":[*dedupe_rejections,*screen_transitions,*amazon_rejections,*selection_transitions],"rejections":[*dedupe_rejections,*screen_rejections,*amazon_rejections,*[x for x in selection_transitions if x["status"]=="REJECTED"]],"serious_candidates":[x["niche"] for x in analyses],"deep_finalists":[x["niche"] for x in deep],"analyses":serious,"normalized_evidence":raw.get("evidence",[]),"source_provenance":raw.get("source_summary",manifest.get("source_summary",{})),"serpapi_usage":usage,"provider_usage":{"serpapi":{"calls_attempted":usage.get("calls_attempted",0),"calls_succeeded":usage.get("calls_succeeded",0),"cache_hits":usage.get("calls_saved_by_cache",0),"provider_cost_usd":usage.get("estimated_cost_usd"),"budget_remaining_calls":usage.get("calls_remaining")},"dataforseo":DATAFORSEO_CALLS},"dataforseo_calls":DATAFORSEO_CALLS,"selection_frozen":True,"selection_frozen_at":now.isoformat(),"selection_model":"CURRENT_PRODUCTION","shadow_model_used_for_selection":False,"production_scores_changed":False}


def write_bundle(bundle: dict[str,Any],directory: str|Path="research/normalized") -> Path:
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); path=directory/f"{stamp}-v1.4c2-prospective-evidence-bundle.json"; path.write_text(json.dumps(bundle,indent=2,ensure_ascii=False,sort_keys=True,default=str),encoding="utf-8"); return path


def dry_run(manifest_path: str|None=None) -> dict[str,Any]:
    if manifest_path: validate_discovery_manifest(json.loads(Path(manifest_path).read_text(encoding="utf-8")))
    output=Path("research/normalized"); output.mkdir(parents=True,exist_ok=True)
    return {"mode":"DRY_RUN","provider_calls":0,"business_filters":BUSINESS_FILTERS,"funnel_targets_not_quotas":FUNNEL_TARGETS,"serpapi_budget":{"environment_variables":["RESEARCH_MAX_PAID_CALLS","RESEARCH_MAX_COST_USD"],"cache":"existing SerpApiCache"},"dataforseo":"DISABLED_BY_COLLECTOR_DESIGN","output_directory":str(output.resolve()),"module_separation":{"production":"amazon_scout.research_pipeline","shadow":"amazon_scout.scoring_calibration_v14c","collector_imports_shadow":False}}


def main(argv: list[str]|None=None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--discovery-manifest"); parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--output-dir",default="research/normalized"); args=parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run(args.discovery_manifest),indent=2)); return 0
    if not args.discovery_manifest: parser.error("--discovery-manifest is required unless --dry-run is used")
    bundle=collect(json.loads(Path(args.discovery_manifest).read_text(encoding="utf-8"))); path=write_bundle(bundle,args.output_dir); f=bundle["funnel"]
    print(f"Bundle:\n{path}\n\nGenerated:\n{f['generated']}\n\nCheap-screened:\n{f['cheap_screened']}\n\nAmazon validated:\n{f['amazon_validated']}\n\nDeep validated:\n{f['deep_validated']}\n\nSerpApi calls:\n{bundle['provider_usage']['serpapi']['calls_attempted']}\n\nDataForSEO calls:\n0\n\nSelection frozen:\nYES"); return 0
