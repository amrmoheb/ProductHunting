from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .evidence import load_bundle
from .research_pipeline import analyze_evidence_bundle, canonical_products_by_asin
from .serpapi_research import run as run_serpapi_validation

VERSION="V1.4C.2A"
MARKETPLACE="amazon.ae"
FUNNEL_TARGETS={"generated":[400,600],"cheap_screen_survivors":[80,120],"serious_amazon_validated":[24,30],"deep_validation_finalists":[10,14]}
BUSINESS_FILTERS={"price_min_aed":50,"price_max_aed":150,"target_net_margin":.25,"preferred_weight_kg_max":1.5,"evergreen":True,"exclude_electronics_batteries":True,"exclude_cosmetics":True,"exclude_supplements":True,"exclude_food_medicine":True,"exclude_fragile_oversized":True}
REJECTION_CODES={"REJECT_PRICE","REJECT_RESTRICTED_CATEGORY","REJECT_RISK","REJECT_RELEVANCE","REJECT_OVERSIZE","REJECT_INSUFFICIENT_EVIDENCE","REJECT_DUPLICATE"}
RESTRICTED={"electronics","battery","batteries","cosmetics","supplement","supplements","food","medicine","medical device","hazardous","adult"}
DATAFORSEO_CALLS={"bulk_search_volume":0,"ranked_keywords":0,"product_competitors":0,"merchant_sellers":0,"total":0}
VALIDATION_LIMIT=30
VALIDATION_MACRO_CAP=3
VALIDATION_STORAGE_CAP=2
DEEP_LIMIT=14
DEEP_MACRO_CAP=2
DEEP_STORAGE_CAP=1
STORAGE_TERMS={"storage","organizer","organiser","organization","organisation"}
MACRO_RULES=(
    ("kitchen_tools",{"kitchen","bakeware","sink","pantry","cutlery","dish"}),
    ("home_cleaning",{"cleaning","cleaner","duster","dusting","mop","brush"}),
    ("laundry_clothing_care",{"laundry","clothing","garment","ironing","wardrobe"}),
    ("travel_accessories",{"travel","luggage","passport","packing","airplane"}),
    ("automotive_accessories",{"car","automotive","vehicle","trunk","visor"}),
    ("office_desk",{"office","desk","document","laptop","cable"}),
    ("crafts_hobby",{"craft","crochet","sewing","knitting","painting"}),
    ("diy_hardware",{"diy","hardware","tool","drill","screw","repair"}),
    ("garden_balcony",{"garden","balcony","plant","watering","hose"}),
    ("pet_accessories",{"pet","dog","cat","leash","litter"}),
    ("fitness_mobility",{"fitness","exercise","yoga","pilates","resistance"}),
    ("personal_accessories",{"personal","jewelry","watch","handbag","shoe"}),
    ("bathroom_accessories",{"bathroom","shower","toilet","soap","towel"}),
    ("outdoor_picnic",{"outdoor","picnic","camping","beach"}),
)


def _semantic_key(name: str) -> str:
    tokens=[token.rstrip("s") for token in "".join(ch.lower() if ch.isalnum() else " " for ch in name).split()]
    return " ".join(sorted(dict.fromkeys(tokens)))


def _normalized_label(value: str) -> str:
    return "_".join(str(value).strip().lower().replace("&"," and ").replace("/"," ").replace("-"," ").split())


def _derive_macro_category(candidate: dict[str,Any]) -> str:
    explicit=candidate.get("macro_category") or candidate.get("category")
    if explicit: return _normalized_label(str(explicit))
    tokens=set(_normalized_label(f"{candidate.get('candidate_name','')} {candidate.get('amazon_keyword','')}").split("_"))
    for category,terms in MACRO_RULES:
        if tokens & terms: return category
    return "household_utility_maintenance"


def _derive_semantic_family(candidate: dict[str,Any]) -> str:
    if candidate.get("semantic_family"): return _normalized_label(str(candidate["semantic_family"]))
    tokens=[token for token in _normalized_label(candidate.get("candidate_name","")).split("_") if token not in {"set","kit","large","small","premium","adjustable","portable","foldable","reusable","multi","pack"}]
    if set(tokens)&STORAGE_TERMS:
        anchors=[token for token in tokens if token not in STORAGE_TERMS and token not in {"rack","tray","box","basket","holder"}]
        return "storage_"+("_".join(anchors[:2]) or "general")
    return "_".join(tokens[:4]) or _normalized_label(candidate["candidate_id"])


def normalize_candidate_taxonomy(candidate: dict[str,Any]) -> dict[str,Any]:
    normalized=dict(candidate)
    normalized["macro_category"]=_derive_macro_category(normalized)
    normalized["semantic_family"]=_derive_semantic_family(normalized)
    normalized["storage_organization_theme"]=bool(
        set(_normalized_label(f"{normalized.get('candidate_name','')} {normalized.get('semantic_family','')}").split("_"))&STORAGE_TERMS
    )
    return normalized


def normalize_candidates(candidates: list[dict[str,Any]]) -> list[dict[str,Any]]:
    return [normalize_candidate_taxonomy(item) for item in candidates]


def category_distribution(candidates: list[dict[str,Any]]) -> dict[str,int]:
    return dict(sorted(Counter(str(item.get("macro_category") or "unknown") for item in candidates).items()))


def semantic_diversity(candidates: list[dict[str,Any]]) -> dict[str,Any]:
    families=Counter(str(item.get("semantic_family") or "unknown") for item in candidates)
    return {"unique_semantic_families":len(families),"family_distribution":dict(sorted(families.items()))}


def allocate_validation_candidates(candidates: list[dict[str,Any]], limit: int=VALIDATION_LIMIT) -> list[dict[str,Any]]:
    normalized=normalize_candidates(candidates); chosen=[]; macros=Counter(); families=set(); storage=0
    grouped={}
    for item in normalized: grouped.setdefault(item["macro_category"],[]).append(item)
    for items in grouped.values():
        items.sort(key=lambda item:(-(float(item.get("discovery_priority") or 0)),item["semantic_family"],item["candidate_id"]))
    while len(chosen)<limit:
        progressed=False
        for macro in sorted(grouped):
            if len(chosen)>=limit: break
            if macros[macro]>=VALIDATION_MACRO_CAP: continue
            while grouped[macro]:
                item=grouped[macro].pop(0); family=item["semantic_family"]; is_storage=item["storage_organization_theme"]
                if family in families or (is_storage and storage>=VALIDATION_STORAGE_CAP): continue
                chosen.append(item); macros[macro]+=1; families.add(family); storage+=int(is_storage); progressed=True; break
        if not progressed: break
    return chosen


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
    # The existing SerpApi runner accepts at most 15 candidates per batch.
    # Allocation remains diversity-aware; larger production hunts orchestrate
    # multiple bounded batches from allocate_validation_candidates(..., 30).
    serious=allocate_validation_candidates(survivors,limit=15)
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
        if justified: eligible.append((-(item.get("data_confidence_score") or 0),-(item.get("opportunity_score") or 0),item.get("macro_category",""),item.get("semantic_family",""),index,item))
    deep=[]; macros=Counter(); families=set(); storage=0
    for entry in sorted(eligible):
        item=entry[-1]; macro=item.get("macro_category","household_utility_maintenance"); family=item.get("semantic_family") or _derive_semantic_family({"candidate_id":item["niche"],"candidate_name":item["niche"]}); is_storage=bool(item.get("storage_organization_theme"))
        if macros[macro]>=DEEP_MACRO_CAP or family in families or (is_storage and storage>=DEEP_STORAGE_CAP): continue
        deep.append(item); macros[macro]+=1; families.add(family); storage+=int(is_storage)
        if len(deep)>=DEEP_LIMIT: break
    selected={item["niche"] for item in deep}
    for transition in transitions:
        if transition["status"]=="ELIGIBLE" and transition["candidate_name"] not in selected:
            transition.update(status="DEFERRED_DIVERSITY_CAP",reason_code="DEFER_DIVERSITY_CAP",reason="Eligible but deferred by deterministic deep-stage category/family allocation.")
    return deep,transitions


def _economics_coverage(item: dict[str,Any]) -> dict[str,Any]:
    economics=item.get("economics") or {}; scenario=(economics.get("scenarios") or {}).get("BASE") or {}; targets=scenario.get("supplier_targets") or {}
    return {"price_basis":item.get("fee_calculation_price_aed"),"referral_fee_aed":scenario.get("referral_fee_aed"),"fulfilment_fba":scenario.get("fba"),"storage_fee_aed":scenario.get("storage_fee_estimate_aed"),"vat":{"amazon_fee_vat_aed":scenario.get("amazon_fee_vat_aed"),"import_vat_cash_flow_aed":scenario.get("import_vat_cash_flow_aed")},"ads_aed":scenario.get("advertising_reserve_aed"),"returns_aed":scenario.get("returns_refunds_reserve_aed"),"inbound_prep_aed":sum(x or 0 for x in (scenario.get("inbound_to_amazon_aed"),scenario.get("inspection_prep_aed"))) if scenario else None,"freight_assumption_aed":(scenario.get("assumptions") or {}).get("international_freight_aed"),"customs_duty_aed":scenario.get("customs_duty_aed"),"physical_profile":economics.get("physical_profile"),"max_landed_cost_25_aed":(scenario.get("maximum_landed_cost_aed") or {}).get("25"),"supplier_product_target_25_aed":(targets.get("25") or {}).get("maximum_supplier_product_cost_aed"),"economics_score":(economics.get("score") or {}).get("raw") if isinstance(economics.get("score"),dict) else economics.get("score"),"economics_confidence":economics.get("confidence"),"economics_status":economics.get("status")}


def collect(manifest: dict[str,Any], *, amazon_validator: Callable[[list[dict[str,Any]],dict[str,Any],Path],dict[str,Any]]|None=None, now: datetime|None=None) -> dict[str,Any]:
    validate_discovery_manifest(manifest); now=now or datetime.now(timezone.utc); generated_candidates=normalize_candidates(manifest["candidates"]); unique,dedupe_rejections=deduplicate_candidates(generated_candidates); survivors,screen_transitions,screen_rejections=screen_candidates(unique)
    with tempfile.TemporaryDirectory(prefix="v14c2a-") as temp:
        validation=(amazon_validator or _default_amazon_validator)(survivors,manifest,Path(temp))
    taxonomy={item["candidate_name"]:item for item in survivors}
    analyses=[]
    for item in validation["analyses"]:
        fallback=normalize_candidate_taxonomy({"candidate_id":item["niche"],"candidate_name":item["niche"],"amazon_keyword":item["niche"]})
        source=taxonomy.get(item["niche"],fallback)
        analyses.append({**item,**{key:source[key] for key in ("macro_category","semantic_family","storage_organization_theme")}})
    amazon_rejections=validation.get("amazon_rejections",[]); deep,selection_transitions=_production_shortlist(analyses); deep_names={x["niche"] for x in deep}
    raw=validation.get("raw",{}); products_by_name={name:canonical_products_by_asin([p for p in raw.get("products",[]) if p.get("niche")==name])[0] for name in {a["niche"] for a in analyses}}
    serious=[]
    for item in analyses:
        snapshot={**item,"products":products_by_name.get(item["niche"],[]),"economics_coverage":_economics_coverage(item),"deep_finalist":item["niche"] in deep_names}
        serious.append(snapshot)
    validation_candidates=[taxonomy[name] for name in {x["niche"] for x in analyses} if name in taxonomy]
    usage=raw.get("serpapi_usage",{}); generated=len(generated_candidates); funnel={"generated":generated,"deduplicated":len(unique),"cheap_screened":len(survivors),"amazon_validated":len(analyses),"deep_validated":len(deep),"economics_validated":sum(_economics_coverage(x)["economics_score"] is not None for x in deep)}
    distributions={"generated":category_distribution(generated_candidates),"cheap_screened":category_distribution(survivors),"amazon_validated":category_distribution(validation_candidates),"deep":category_distribution(deep)}
    diversity={"generated":semantic_diversity(generated_candidates),"cheap_screened":semantic_diversity(survivors),"amazon_validated":semantic_diversity(validation_candidates),"deep":semantic_diversity(deep)}
    if not (generated>=len(unique)>=len(survivors)>=len(analyses)>=len(deep)): raise ValueError("Prospective funnel invariant violated")
    return {"metadata":{"version":VERSION,"marketplace":MARKETPLACE,"generated_at":now.isoformat(),"selection_frozen":True,"selection_frozen_at":now.isoformat(),"selection_model":"CURRENT_PRODUCTION","shadow_model_used_for_selection":False,"collector_network_policy":"SERPAPI_PUBLIC_AMAZON_ONLY; DATAFORSEO_FORBIDDEN"},"research_run":{"id":f"v14c2a-{now:%Y%m%d%H%M%S}","slug":"v1.4c2-prospective-evidence-bundle","marketplace":MARKETPLACE,"started_at":manifest.get("generated_at") or now.isoformat(),"evidence_cutoff":now.isoformat(),"filters":BUSINESS_FILTERS,"candidate_funnel":funnel},"funnel_targets_not_quotas":FUNNEL_TARGETS,"funnel":funnel,"category_distribution":distributions,"semantic_diversity":diversity,"generated_candidates":generated_candidates,"stage_transitions":[*dedupe_rejections,*screen_transitions,*amazon_rejections,*selection_transitions],"rejections":[*dedupe_rejections,*screen_rejections,*amazon_rejections,*[x for x in selection_transitions if x["status"]=="REJECTED"]],"serious_candidates":[x["niche"] for x in analyses],"deep_finalists":[x["niche"] for x in deep],"analyses":serious,"normalized_evidence":raw.get("evidence",[]),"source_provenance":raw.get("source_summary",manifest.get("source_summary",{})),"serpapi_usage":usage,"provider_usage":{"serpapi":{"calls_attempted":usage.get("calls_attempted",0),"calls_succeeded":usage.get("calls_succeeded",0),"cache_hits":usage.get("calls_saved_by_cache",0),"provider_cost_usd":usage.get("estimated_cost_usd"),"budget_remaining_calls":usage.get("calls_remaining")},"dataforseo":DATAFORSEO_CALLS},"dataforseo_calls":DATAFORSEO_CALLS,"selection_frozen":True,"selection_frozen_at":now.isoformat(),"selection_model":"CURRENT_PRODUCTION","shadow_model_used_for_selection":False,"production_scores_changed":False}


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
