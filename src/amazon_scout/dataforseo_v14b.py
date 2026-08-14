from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from .dataforseo_audit import POC_KEYWORDS, select_representative_asins
from .sources.dataforseo import (ENDPOINTS, DataForSEOBudget, DataForSEOCache,
 DataForSEOMode, DataForSEOProviderError, DataForSEOSettings, DataForSEOSource, EvidenceEnvironment,
 parse_bulk_search_volume, parse_product_competitors, parse_ranked_keywords)

MARKETPLACE_ID="A2VIGQ35RCS4UG"
LOCATION_CODE=2784
LANGUAGE_CODE="ar"
ENGLISH_COVERAGE="NOT_CONFIRMED"
LANGUAGE_COVERAGE="PARTIAL_AMAZON_UAE_LANGUAGE_COVERAGE"
CANDIDATES=tuple(POC_KEYWORDS)
DEFAULT_RAW=Path("research/raw/2026-08-12-resumed-diversified-hunt-v13-economics-evidence.json")
DEFAULT_NORMALIZED=Path("research/normalized/2026-08-12-075921-resumed-diversified-hunt-v1.3-economics-audit.json")

ARABIC_KEYWORD_CLUSTERS={
 "long handle baseboard cleaning tool":[
  ("baseboard cleaner tool with handle","أداة تنظيف حواف الجدران","buyer-intent product term"),
  ("baseboard cleaning tool","ممسحة حواف الجدران","common ecommerce product synonym"),
  ("baseboard cleaning brush","فرشاة تنظيف الوزرة","Gulf building-trim terminology"),
  ("long handle wall mop","ممسحة جدران بمقبض طويل","feature-led shopping term")],
 "wood crochet blocking board":[
  ("wood crochet blocking board","لوح تثبيت الكروشيه","buyer-intent product term"),
  ("crochet blocking board","لوح بلوكينغ كروشيه","common borrowed craft terminology"),
  ("granny square blocking board","لوح مربعات الكروشيه","use-case shopping term"),
  ("wood board for crochet","لوح خشبي للكروشيه","material-led shopping term")],
 "washable ceiling fan blade sleeve duster":[
  ("ceiling fan blade duster","منظف ريش مروحة السقف","buyer-intent product term"),
  ("ceiling fan cleaning sleeve","غطاء تنظيف مروحة السقف","sleeve-format shopping term"),
  ("ceiling fan mop","ممسحة مروحة سقف","common cleaning-product synonym"),
  ("ceiling fan cleaning brush","فرشاة تنظيف مروحة السقف","buyer-intent product synonym")],
 "adjustable airplane foot hammock":[
  ("airplane footrest","مسند قدم للطائرة","common travel-shopping term"),
  ("airplane foot hammock","أرجوحة قدم للطائرة","target product term"),
  ("travel footrest","مسند قدم للسفر","broader buyer-intent synonym"),
  ("airplane foot support","دعامة قدم للطائرة","benefit-led shopping term")],
 "foldable calf slant board":[
  ("calf slant board","لوح مائل لتمديد الساق","buyer-intent product term"),
  ("calf stretching board","لوح إطالة عضلة الساق","use-case shopping term"),
  ("incline exercise board","لوح تمارين مائل","fitness ecommerce synonym"),
  ("calf stretch board","لوح تمدد ربلة الساق","anatomically specific shopping term")],
}

def keyword_records() -> list[dict[str,str]]:
    rows=[]
    for candidate,cluster in ARABIC_KEYWORD_CLUSTERS.items():
        for index,(english,arabic,intent) in enumerate(cluster):
            rows.append({"candidate":candidate,"original_english_keyword":english,"arabic_keyword":arabic,"translation_research_provenance":"curated UAE/Gulf Arabic ecommerce terminology; human-review required before scaling","keyword_intent":intent,"primary":index==0})
    return rows

def bulk_task() -> dict[str,Any]:
    return {"keywords":list(dict.fromkeys(row["arabic_keyword"] for row in keyword_records())),"location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE}

def poc_settings() -> DataForSEOSettings:
    base=DataForSEOSettings.from_environment()
    return DataForSEOSettings(base.mode,base.allow_paid,max(0,float(os.getenv("DATAFORSEO_V14B_MAX_COST_USD","0.20"))),max(0,int(os.getenv("DATAFORSEO_V14B_MAX_TASKS","12"))),base.login,base.password)

def load_inputs(raw_path: Path=DEFAULT_RAW, normalized_path: Path=DEFAULT_NORMALIZED) -> tuple[dict[str,Any],dict[str,Any]]:
    return json.loads(raw_path.read_text()),json.loads(normalized_path.read_text())

def representative_mapping(raw: dict[str,Any]) -> dict[str,list[dict[str,Any]]]:
    mapping={}
    for candidate in CANDIDATES:
        products=[]; seen=set()
        for product in raw["products"]:
            if product.get("niche")!=candidate or product.get("asin") in seen: continue
            seen.add(product.get("asin")); products.append(product)
        selected=select_representative_asins(products,3); by_asin={p.get("asin"):p for p in products}
        mapping[candidate]=[{**item,"candidate":candidate,"current_price_aed":by_asin[item["asin"]].get("current_price_aed"),"rating":by_asin[item["asin"]].get("rating"),"reviews":by_asin[item["asin"]].get("reviews")} for item in selected]
    return mapping

def _old_mapping(normalized: dict[str,Any]) -> dict[str,dict[str,Any]]:
    return {a["niche"]:a for a in normalized["analyses"] if a["niche"] in CANDIDATES}

def _safe_call(source,endpoint,task,budget,cache,parser,failures):
    if budget.tasks_attempted>=budget.max_tasks: failures.append({"endpoint":endpoint,"status":"SKIPPED_LOCAL_TASK_BUDGET"}); return None
    try:
        payload,cached=source.request(endpoint,task,budget,cache,estimated_cost=.02)
        failures.append({"endpoint":endpoint,"status":"SUCCEEDED","cached":cached}); return parser(payload,EvidenceEnvironment.PRODUCTION),cached
    except PermissionError as exc: failures.append({"endpoint":endpoint,"status":"SKIPPED_LOCAL_TASK_BUDGET","reason":str(exc)}); return None
    except DataForSEOProviderError as exc:
        status="UNSUPPORTED" if exc.status_name in {"FUNCTION_UNAVAILABLE","OUTDATED_LOCATION_DATA"} else "FAILED"
        failures.append({"endpoint":endpoint,"status":status,"reason":str(exc)}); return None
    except Exception as exc: failures.append({"endpoint":endpoint,"status":"FAILED","reason":str(exc)}); return None

def volume_status(row: dict[str,Any] | None) -> str:
    if row is None or not row.get("search_volume_present",False): return "MISSING_FIELD"
    value=row.get("search_volume")
    if value is None: return "NULL_PROVIDER_VOLUME"
    if isinstance(value,(int,float)) and not isinstance(value,bool): return "ZERO_VOLUME" if value==0 else "NUMERIC_VOLUME"
    return "MISSING_FIELD"

def _volume_audit(candidate,volume_by_keyword):
    rows=[]
    for source in keyword_records():
        if source["candidate"]!=candidate: continue
        provider_row=volume_by_keyword.get(source["arabic_keyword"]); status=volume_status(provider_row); value=provider_row.get("search_volume") if provider_row else None
        rows.append({**source,"keyword":source["arabic_keyword"],"search_volume":value,"amazon_monthly_search_volume":value,"volume_status":status,"provider":"dataforseo_amazon_labs","location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE,"environment":"PRODUCTION"})
    values=[r["search_volume"] for r in rows if r["volume_status"] in {"NUMERIC_VOLUME","ZERO_VOLUME"}]
    counts={name:sum(r["volume_status"]==name for r in rows) for name in ("NUMERIC_VOLUME","ZERO_VOLUME","NULL_PROVIDER_VOLUME","MISSING_FIELD")}
    return {"primary_keyword_volume":rows[0]["search_volume"],"keyword_volumes":rows,"normalized_keyword_rows":rows,"numeric_volume_count":counts["NUMERIC_VOLUME"],"zero_volume_count":counts["ZERO_VOLUME"],"null_volume_count":counts["NULL_PROVIDER_VOLUME"],"missing_volume_count":counts["MISSING_FIELD"],"median_keyword_volume":median(values) if values else None,"maximum_keyword_volume":max(values) if values else None,"cluster_total":None,"cluster_total_status":"UNKNOWN_OVERLAP_NOT_DEDUPLICATED","status":"NUMERIC_PROVIDER_VOLUME_DATA" if values else "NO_PROVIDER_VOLUME_DATA"}

def run_poc(*, source=None, cache=None, raw=None, normalized=None, now=None) -> dict[str,Any]:
    settings=poc_settings()
    if settings.mode!=DataForSEOMode.PRODUCTION or not settings.allow_paid: raise PermissionError("V1.4B production POC requires DATAFORSEO_MODE=production and DATAFORSEO_ALLOW_PAID=true")
    raw,normalized=(raw,normalized) if raw is not None and normalized is not None else load_inputs()
    source=source or DataForSEOSource(settings); cache=cache or DataForSEOCache(); budget=DataForSEOBudget.from_settings(settings); failures=[]; reps=representative_mapping(raw)
    bulk=_safe_call(source,ENDPOINTS["bulk_search_volume"],bulk_task(),budget,cache,parse_bulk_search_volume,failures)
    volume_rows=bulk[0] if bulk else []; volume_by_keyword={r["keyword"]:r for r in volume_rows}; ranked={c:[] for c in CANDIDATES}; competitors={c:[] for c in CANDIDATES}; competition_outcomes={c:"NOT_RUN" for c in CANDIDATES}
    old=_old_mapping(normalized); candidates=[]
    for candidate in CANDIDATES:
        baseline=old[candidate]; volumes=_volume_audit(candidate,volume_by_keyword)
        candidates.append({"candidate":candidate,"official_scores_unchanged":True,"current_engine":{"demand_score":baseline.get("demand_score"),"demand_status":baseline.get("demand_status"),"demand_confidence":baseline.get("demand_confidence"),"competition_score":baseline.get("competition_score"),"competition_status":baseline.get("competition_status"),"competition_confidence":baseline.get("competition_confidence"),"official_opportunity_score":baseline.get("opportunity_score"),"validated_opportunity_score":baseline.get("validated_opportunity_score")},"representative_asins":reps[candidate],"dataforseo_audit":{"arabic_amazon_keyword_evidence":volumes,"ranked_keyword_observations":ranked[candidate],"competitor_observations":competitors[candidate],"competition_endpoint_outcome":competition_outcomes[candidate],"competition_evidence":"NOT_RUN" if competition_outcomes[candidate] in {"NOT_RUN","SKIPPED_LOCAL_TASK_BUDGET"} else competition_outcomes[candidate],"language_coverage":LANGUAGE_COVERAGE,"english_coverage":ENGLISH_COVERAGE,"evidence_confidence":"PARTIAL" if volume_rows else "INSUFFICIENT"},"demand_audit_conclusion":"INSUFFICIENT_DATA","competition_audit_conclusion":"INSUFFICIENT_DATA","special_demand_86_25_audit":"Arabic-only coverage is insufficient to confirm equal whole-market demand strength."})
    usage=budget.as_dict(); usage["total_provider_reported_cost"]=usage["provider_reported_cost"]
    unsuccessful=[outcome for outcome in failures if outcome["status"]!="SUCCEEDED"]
    return {"version":"V1.4B.1","generated_at":(now or datetime.now(timezone.utc)).isoformat(),"marketplace":"amazon.ae","marketplace_id":MARKETPLACE_ID,"location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE,"DATAFORSEO_AMAZON_UAE_ENGLISH_COVERAGE":ENGLISH_COVERAGE,"coverage":LANGUAGE_COVERAGE,"candidates":candidates,"provider_usage":usage,"endpoint_outcomes":failures,"failed_or_unsupported_endpoints":unsuccessful,"merchant_sellers_calls":0,"official_scores_changed":False}

def render_report(bundle: dict[str,Any]) -> str:
    usage=bundle["provider_usage"]
    lines=["# DATAFORSEO AMAZON UAE REAL-DATA POC — V1.4B","",f"Generated: {bundle['generated_at']}","Marketplace: Amazon.ae (`A2VIGQ35RCS4UG`)","Coverage: PARTIAL_AMAZON_UAE_LANGUAGE_COVERAGE; Arabic (`ar`) only. English Amazon Labs coverage is NOT_CONFIRMED.","Official opportunity scoring: UNCHANGED.","","| Candidate | Current demand | Arabic Amazon keyword evidence | Demand audit | Current competition | DataForSEO competition evidence | Competition audit | Coverage | Provider cost |","|---|---:|---|---|---:|---|---|---|---:|"]
    for item in bundle["candidates"]:
        audit=item["dataforseo_audit"]; v=audit["arabic_amazon_keyword_evidence"]; volume_text=", ".join(f"{x['arabic_keyword']}: {x['volume_status']}"+(f" ({x['search_volume']})" if x['search_volume'] is not None else "") for x in v["keyword_volumes"]); comp_text=f"{len(audit['competitor_observations'])} competitor rows" if audit["competition_endpoint_outcome"]=="SUCCEEDED" else "NOT_RUN" if audit["competition_endpoint_outcome"] in {"NOT_RUN","SKIPPED_LOCAL_TASK_BUDGET"} else audit["competition_endpoint_outcome"]
        lines.append(f"| {item['candidate']} | {item['current_engine']['demand_score']} | {volume_text}; numeric {v['numeric_volume_count']}; zero {v['zero_volume_count']}; null {v['null_volume_count']}; missing {v['missing_volume_count']}; median {v['median_keyword_volume'] if v['median_keyword_volume'] is not None else 'N/A'}; max {v['maximum_keyword_volume'] if v['maximum_keyword_volume'] is not None else 'N/A'}; status {v['status']}; cluster total UNKNOWN | {item['demand_audit_conclusion']} | {item['current_engine']['competition_score']} | {comp_text} | {item['competition_audit_conclusion']} | {LANGUAGE_COVERAGE} | Included in run total |")
    lines += ["",f"POC total provider cost: USD {usage['provider_reported_cost']:.8f}",f"Account calls performed: {usage['tasks_attempted']}",f"Cache hits: {usage['cache_hits']}",f"Items returned: {usage['items_returned']}",f"Budget remaining: USD {usage['remaining_local_cost_budget']:.8f}; {usage['remaining_local_task_budget']} tasks",f"Endpoint outcomes: {json.dumps(bundle['endpoint_outcomes'],ensure_ascii=False)}","Merchant Sellers production calls: 0","","Arabic absolute search volume is not merged with English SerpApi/public Amazon proxy evidence. Cluster totals remain UNKNOWN because overlap is not deduplicated."]
    return "\n".join(lines)+"\n"

def write_outputs(bundle, directory="reports"):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); base=directory/f"{stamp}-v1.4b-dataforseo-amazon-uae-poc"; md=base.with_suffix(".md"); js=base.with_suffix(".json"); md.write_text(render_report(bundle),encoding="utf-8"); js.write_text(json.dumps(bundle,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8"); return md,js

def main():
    try: bundle=run_poc()
    except (PermissionError,ValueError) as exc: print(f"REFUSED: {exc}"); return 2
    md,js=write_outputs(bundle); print(f"Report: {md}"); print(f"Evidence: {js}"); print(f"Provider cost: USD {bundle['provider_usage']['provider_reported_cost']:.8f}"); return 0
