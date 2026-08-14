import copy
import json
from datetime import datetime, timezone
from unittest.mock import patch

from amazon_scout.prospective_collector_v14c2a import (
    BUSINESS_FILTERS, DATAFORSEO_CALLS, FUNNEL_TARGETS, REJECTION_CODES,
    _default_amazon_validator, collect, deduplicate_candidates, dry_run,
    screen_candidates, write_bundle,
)
from amazon_scout.prospective_shadow_v14c2 import run_shadow_validation, validate_bundle
from amazon_scout.scoring_calibration_v14c import load_artifacts


NOW=datetime(2026,8,14,tzinfo=timezone.utc)


def candidate(index,name=None,**extra):
    return {"candidate_id":f"idea-{index:03d}","candidate_name":name or f"prospective niche {index}","query_source":f"Codex web discovery query {index}","discovered_at":NOW.isoformat(),"marketplace":"amazon.ae","generation_reason":"Current UAE shopping/use-case discovery evidence","amazon_keyword":name or f"prospective niche {index}",**extra}


def manifest(count=60): return {"marketplace":"amazon.ae","generated_at":NOW.isoformat(),"candidates":[candidate(i) for i in range(count)],"evidence":[],"products":[],"source_summary":{"Codex live web search":"USED"}}


def analyses(count=6): return copy.deepcopy(load_artifacts()["v13"]["analyses"][:count])


def validator(rows,manifest,workdir,analysis_rows=None):
    selected=copy.deepcopy(analysis_rows or analyses())
    products=[]
    for item in selected: products.extend(item.get("products") or [])
    return {"raw":{"products":products,"evidence":[],"source_summary":{"SerpApi":"FIXTURE"},"serpapi_usage":{"configured":True,"enabled":True,"configured_max_calls":15,"calls_attempted":len(selected),"calls_succeeded":len(selected),"calls_failed":0,"calls_saved_by_cache":2,"calls_remaining":15-len(selected),"estimated_cost_usd":0}},"analyses":selected}


def test_funnel_targets_are_ranges_not_quotas():
    assert FUNNEL_TARGETS=={"generated":[50,80],"cheap_screen_survivors":[20,30],"serious_amazon_validated":[10,15],"deep_validation_finalists":[5,10]}
    assert BUSINESS_FILTERS["price_min_aed"]==50 and BUSINESS_FILTERS["price_max_aed"]==150


def test_no_forced_finalists():
    rows=analyses(3)
    for row in rows: row["gates"]["demand"]["gate"]=False
    bundle=collect(manifest(),amazon_validator=lambda a,b,c:validator(a,b,c,rows),now=NOW)
    assert bundle["deep_finalists"]==[] and bundle["funnel"]["deep_validated"]==0


def test_deterministic_semantic_deduplication_and_rejection_reason():
    items=[candidate(1,"metal bag hooks"),candidate(2,"bag hook metals"),candidate(3,"towel clips")]
    first,rejected=deduplicate_candidates(items); second,_=deduplicate_candidates(items)
    assert [x["candidate_id"] for x in first]==[x["candidate_id"] for x in second]==["idea-001","idea-003"]
    assert rejected[0]["reason_code"]=="REJECT_DUPLICATE"


def test_every_stage_a_rejection_has_deterministic_reason():
    items=[candidate(1,category="electronics"),candidate(2,observed_or_estimated_price_aed=20),candidate(3,fragile=True),candidate(4,oversized=True),candidate(5,is_irrelevant=True),{**candidate(6),"amazon_keyword":""}]
    _,_,rejections=screen_candidates(items)
    assert len(rejections)==6 and all(r["reason_code"] in REJECTION_CODES and r["reason"] for r in rejections)


def test_current_production_score_drives_selection_not_shadow():
    rows=analyses(6)
    expected=[x["niche"] for x in rows if x["gates"]["price"]["gate"] and x["gates"]["demand"]["gate"] and x["gates"]["competition"]["gate"]]
    with patch("amazon_scout.scoring_calibration_v14c.calibrate_candidate",side_effect=AssertionError("shadow forbidden")):
        bundle=collect(manifest(),amazon_validator=lambda a,b,c:validator(a,b,c,rows),now=NOW)
    assert set(bundle["deep_finalists"])==set(expected)
    assert bundle["selection_model"]=="CURRENT_PRODUCTION" and bundle["shadow_model_used_for_selection"] is False


def test_dataforseo_is_always_zero_and_no_network_in_fixture_run():
    with patch("urllib.request.urlopen",side_effect=AssertionError("provider network forbidden")) as network:
        bundle=collect(manifest(),amazon_validator=validator,now=NOW)
    assert network.call_count==0 and bundle["dataforseo_calls"]==DATAFORSEO_CALLS
    assert bundle["provider_usage"]["dataforseo"]["total"]==0


def test_existing_serpapi_usage_and_cache_accounting_preserved():
    bundle=collect(manifest(),amazon_validator=validator,now=NOW); usage=bundle["provider_usage"]["serpapi"]
    assert usage["calls_attempted"]==6 and usage["calls_succeeded"]==6 and usage["cache_hits"]==2
    assert usage["budget_remaining_calls"]==9


def test_exact_close_only_and_unique_asin_statistics_preserved():
    rows=analyses(1); row=rows[0]; product=copy.deepcopy(row["products"][0]); row["products"].append(product)
    bundle=collect(manifest(),amazon_validator=lambda a,b,c:validator(a,b,c,rows),now=NOW); saved=bundle["analyses"][0]
    asins=[p["asin"] for p in saved["products"] if p.get("asin")]
    assert len(asins)==len(set(asins))
    relevance=saved["relevance_summary"]
    assert relevance["target_results"]==relevance["exact_results"]+relevance["close_variants"]


def test_no_missing_price_or_economics_fabrication():
    rows=analyses(1); row=rows[0]; row["fee_calculation_price_aed"]=None; row["economics"]={"status":"INSUFFICIENT","confidence":20,"score":{"raw":None},"physical_profile":None}
    bundle=collect(manifest(),amazon_validator=lambda a,b,c:validator(a,b,c,rows),now=NOW); saved=bundle["analyses"][0]
    assert saved["fee_calculation_price_aed"] is None
    assert saved["economics_coverage"]["price_basis"] is None and saved["economics_coverage"]["economics_score"] is None and saved["economics_coverage"]["physical_profile"] is None


def test_funnel_arithmetic_and_frozen_metadata():
    bundle=collect(manifest(),amazon_validator=validator,now=NOW); f=bundle["funnel"]
    assert f["generated"]>=f["deduplicated"]>=f["cheap_screened"]>=f["amazon_validated"]>=f["deep_validated"]
    assert bundle["selection_frozen"] and bundle["selection_frozen_at"]==NOW.isoformat()
    assert bundle["metadata"]["selection_model"]=="CURRENT_PRODUCTION" and bundle["production_scores_changed"] is False


def test_bundle_accepted_by_shadow_parser_and_frozen_shortlist_respected(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE","disabled"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","false")
    bundle=collect(manifest(),amazon_validator=validator,now=NOW); validate_bundle(bundle); result=run_shadow_validation(bundle,now=NOW)
    assert result["selection_snapshot"]==bundle["deep_finalists"]


def test_write_bundle_path_and_dry_run_zero_calls(tmp_path):
    bundle=collect(manifest(),amazon_validator=validator,now=NOW); path=write_bundle(bundle,tmp_path)
    assert path.name.endswith("-v1.4c2-prospective-evidence-bundle.json")
    with patch("urllib.request.urlopen",side_effect=AssertionError("network forbidden")) as network: diagnostic=dry_run()
    assert network.call_count==0 and diagnostic["provider_calls"]==0
    assert diagnostic["module_separation"]["collector_imports_shadow"] is False and diagnostic["dataforseo"]=="DISABLED_BY_COLLECTOR_DESIGN"


def _runner_bundle(path, rows, *, evidence=None, usage=None):
    path.write_text(json.dumps({
        "research_run":{"id":"test","slug":"test","marketplace":"amazon.ae","started_at":NOW.isoformat(),"evidence_cutoff":NOW.isoformat(),"filters":BUSINESS_FILTERS,"candidate_funnel":{"generated":len(rows),"screened":len(rows)}},
        "keywords":[row["amazon_keyword"] for row in rows],"products":[],"evidence":evidence or [],
        "source_summary":{"SerpApi":"USED" if evidence else "FAILED"},"provider_errors":[],
        "serpapi_usage":usage or {"calls_attempted":len(rows),"calls_succeeded":0,"calls_failed":len(rows),"calls_saved_by_cache":0,"calls_remaining":0,"estimated_cost_usd":0},
    }),encoding="utf-8")


def test_regression_research_runner_precedes_load_bundle(tmp_path):
    rows=[candidate(1,"drawer organizer")]; order=[]
    def runner(queries, *, output, max_calls, base_bundle):
        order.append(("runner",queries,max_calls)); _runner_bundle(output,rows,evidence=[{"id":"e-1"}]); return output
    with patch("amazon_scout.prospective_collector_v14c2a.run_serpapi_validation",side_effect=runner), patch("amazon_scout.prospective_collector_v14c2a.load_bundle",side_effect=lambda path:(order.append(("load",)),({},[]))[1]), patch("amazon_scout.prospective_collector_v14c2a.analyze_evidence_bundle",return_value=[]):
        _default_amazon_validator(rows,manifest(1),tmp_path)
    assert order[0]==("runner",[("drawer organizer","drawer organizer")],15)
    assert order[1]==("load",)


def test_zero_evidence_candidate_is_rejected_without_loading(tmp_path):
    rows=[candidate(1,"drawer organizer")]
    def runner(queries, *, output, max_calls, base_bundle):
        _runner_bundle(output,rows); return output
    with patch("amazon_scout.prospective_collector_v14c2a.run_serpapi_validation",side_effect=runner), patch("amazon_scout.prospective_collector_v14c2a.load_bundle",side_effect=AssertionError("empty bundle must not be loaded")):
        result=_default_amazon_validator(rows,manifest(1),tmp_path)
    assert result["analyses"]==[]
    assert result["amazon_rejections"]==[{"candidate_id":"idea-001","candidate_name":"drawer organizer","stage":"STAGE_B_AMAZON_VALIDATION","status":"REJECTED","reason_code":"REJECT_INSUFFICIENT_EVIDENCE","reason":"Amazon UAE validation returned zero evidence for this candidate"}]


def test_all_zero_evidence_returns_valid_frozen_bundle(tmp_path):
    def runner(queries, *, output, max_calls, base_bundle):
        _runner_bundle(output,manifest(3)["candidates"],usage={"calls_attempted":2,"calls_succeeded":0,"calls_failed":2,"calls_saved_by_cache":1,"calls_remaining":3,"estimated_cost_usd":0}); return output
    with patch("amazon_scout.prospective_collector_v14c2a.run_serpapi_validation",side_effect=runner), patch("amazon_scout.prospective_collector_v14c2a.load_bundle",side_effect=AssertionError("empty bundle must not be loaded")):
        bundle=collect(manifest(3),now=NOW)
    assert bundle["funnel"]["amazon_validated"]==bundle["funnel"]["deep_validated"]==0
    assert len([x for x in bundle["rejections"] if x["stage"]=="STAGE_B_AMAZON_VALIDATION"])==3
    assert bundle["selection_frozen"] and bundle["dataforseo_calls"]["total"]==0
    assert bundle["provider_usage"]["serpapi"]=={"calls_attempted":2,"calls_succeeded":0,"cache_hits":1,"provider_cost_usd":0,"budget_remaining_calls":3}


def test_default_validator_delegates_local_limits_and_cache_to_existing_runner(tmp_path,monkeypatch):
    monkeypatch.setenv("RESEARCH_MAX_PAID_CALLS","7"); monkeypatch.setenv("RESEARCH_MAX_COST_USD","0.03")
    rows=[candidate(i) for i in range(20)]; captured={}
    def runner(queries, *, output, max_calls, base_bundle):
        captured.update(queries=queries,max_calls=max_calls,call_limit=__import__('os').environ["RESEARCH_MAX_PAID_CALLS"],cost_limit=__import__('os').environ["RESEARCH_MAX_COST_USD"])
        _runner_bundle(output,rows,usage={"calls_attempted":0,"calls_succeeded":0,"calls_failed":0,"calls_saved_by_cache":7,"calls_remaining":7,"estimated_cost_usd":0}); return output
    with patch("amazon_scout.prospective_collector_v14c2a.run_serpapi_validation",side_effect=runner):
        result=_default_amazon_validator(rows,manifest(20),tmp_path)
    assert len(captured["queries"])==15 and captured["max_calls"]==15
    assert captured["call_limit"]=="7" and captured["cost_limit"]=="0.03"
    assert result["raw"]["serpapi_usage"]["calls_saved_by_cache"]==7
