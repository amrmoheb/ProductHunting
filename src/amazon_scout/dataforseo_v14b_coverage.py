from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dataforseo_v14b import LOCATION_CODE, LANGUAGE_CODE, volume_status
from .sources.dataforseo import (ENDPOINTS, DataForSEOBudget, DataForSEOCache,
 DataForSEOMode, DataForSEOSettings, DataForSEOSource, EvidenceEnvironment,
 parse_bulk_search_volume)

COVERAGE_KEYWORDS=["حقيبة سفر","كروشيه","مروحة سقف","مسند قدم","تنظيف الجدران","لوح تمارين"]
CONTROL_KEYWORD="حقيبة سفر"
KEYWORD_CONCEPTS={
 "حقيبة سفر":"CONTROL_COMMON_ECOMMERCE",
 "كروشيه":"wood crochet blocking board",
 "مروحة سقف":"washable ceiling fan blade sleeve duster",
 "مسند قدم":"adjustable airplane foot hammock",
 "تنظيف الجدران":"long handle baseboard cleaning tool",
 "لوح تمارين":"foldable calf slant board",
}

def coverage_task() -> dict[str,Any]: return {"keywords":COVERAGE_KEYWORDS.copy(),"location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE}

def coverage_settings() -> DataForSEOSettings:
    base=DataForSEOSettings.from_environment()
    max_cost=min(.025,max(0,float(os.getenv("DATAFORSEO_V14B_COVERAGE_MAX_COST_USD","0.025"))))
    max_tasks=min(1,max(0,int(os.getenv("DATAFORSEO_V14B_COVERAGE_MAX_TASKS","1"))))
    return DataForSEOSettings(base.mode,base.allow_paid,max_cost,max_tasks,base.login,base.password)

def normalize_rows(provider_rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    by_keyword={row.get("keyword"):row for row in provider_rows}
    rows=[]
    for keyword in COVERAGE_KEYWORDS:
        provider=by_keyword.get(keyword); status=volume_status(provider)
        rows.append({"candidate":KEYWORD_CONCEPTS[keyword],"keyword":keyword,"search_volume":provider.get("search_volume") if provider else None,"volume_status":status,"provider":"dataforseo_amazon_labs","location_code":LOCATION_CODE,"language_code":LANGUAGE_CODE,"environment":"PRODUCTION"})
    return rows

def interpret(rows: list[dict[str,Any]]) -> str:
    by_keyword={row["keyword"]:row for row in rows}; control=by_keyword[CONTROL_KEYWORD]["volume_status"]
    head=[row for row in rows if row["keyword"]!=CONTROL_KEYWORD]; numeric={"NUMERIC_VOLUME","ZERO_VOLUME"}; absent={"NULL_PROVIDER_VOLUME","MISSING_FIELD"}
    numeric_heads=sum(row["volume_status"] in numeric for row in head); absent_heads=sum(row["volume_status"] in absent for row in head)
    if control in numeric and numeric_heads>=3: return "ARABIC_AMAZON_VOLUME_DATASET_USABLE_ORIGINAL_KEYWORDS_LIKELY_TOO_NARROW"
    if control in numeric and absent_heads>=3: return "PROVIDER_WORKS_CANDIDATE_CONCEPTS_WEAK_OR_TOO_SPARSE_TO_MEASURE"
    if control in absent and sum(row["volume_status"] in absent for row in rows)>=4: return "ARABIC_AMAZON_UAE_VOLUME_COVERAGE_NOT_USEFUL_FOR_PRODUCT_HUNTING_DEMAND_MODEL"
    return "INCONCLUSIVE_COVERAGE_DIAGNOSTIC"

def run_coverage_probe(*,source=None,cache=None,now=None) -> dict[str,Any]:
    settings=coverage_settings()
    if settings.mode!=DataForSEOMode.PRODUCTION or not settings.allow_paid: raise PermissionError("V1.4B.1 coverage probe requires DATAFORSEO_MODE=production and DATAFORSEO_ALLOW_PAID=true")
    if settings.max_tasks_per_run!=1 or settings.max_cost_usd_per_run<=0: raise PermissionError("V1.4B.1 coverage probe local task/cost guard does not permit its one task")
    source=source or DataForSEOSource(settings); cache=cache or DataForSEOCache(); budget=DataForSEOBudget.from_settings(settings)
    payload,cached=source.request(ENDPOINTS["bulk_search_volume"],coverage_task(),budget,cache,estimated_cost=.0144)
    rows=normalize_rows(parse_bulk_search_volume(payload,EvidenceEnvironment.PRODUCTION)); usage=budget.as_dict()
    return {"version":"V1.4B.1","generated_at":(now or datetime.now(timezone.utc)).isoformat(),"purpose":"COVERAGE_DIAGNOSTIC_ONLY_NOT_CANDIDATE_SCORING","official_scores_changed":False,"task":coverage_task(),"control_keyword":CONTROL_KEYWORD,"normalized_keyword_rows":rows,"interpretation":interpret(rows),"provider_usage":usage,"cache_hit":cached,"ranked_keywords_calls":0,"product_competitors_calls":0}

def render_coverage_report(bundle):
    lines=["# DATAFORSEO UAE ARABIC SEARCH-VOLUME COVERAGE DIAGNOSTIC — V1.4B.1","","Official scoring: UNCHANGED.","Purpose: provider coverage diagnostic only; broad terms do not become candidate demand evidence.",f"Control keyword: {CONTROL_KEYWORD}","","| Concept | Keyword | Search volume | Volume status |","|---|---|---:|---|"]
    for row in bundle["normalized_keyword_rows"]: lines.append(f"| {row['candidate']} | {row['keyword']} | {row['search_volume'] if row['search_volume'] is not None else 'N/A'} | {row['volume_status']} |")
    usage=bundle["provider_usage"]; lines += ["",f"Interpretation: **{bundle['interpretation']}**",f"Provider cost: USD {usage['provider_reported_cost']:.8f}",f"Tasks attempted: {usage['tasks_attempted']}",f"Cache hits: {usage['cache_hits']}","Ranked Keywords calls: 0","Product Competitors calls: 0"]
    return "\n".join(lines)+"\n"

def write_coverage_outputs(bundle,directory="reports"):
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y-%m-%d-%H%M%S"); base=directory/f"{stamp}-v1.4b1-dataforseo-uae-arabic-coverage"; md=base.with_suffix(".md"); js=base.with_suffix(".json"); md.write_text(render_coverage_report(bundle),encoding="utf-8"); js.write_text(json.dumps(bundle,indent=2,ensure_ascii=False,sort_keys=True),encoding="utf-8"); return md,js

def main():
    try: bundle=run_coverage_probe()
    except (PermissionError,ValueError) as exc: print(f"REFUSED: {exc}"); return 2
    md,js=write_coverage_outputs(bundle); print(f"Report: {md}"); print(f"Evidence: {js}"); print(f"Interpretation: {bundle['interpretation']}"); return 0
