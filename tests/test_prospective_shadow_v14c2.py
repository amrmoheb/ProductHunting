import copy
import json
from datetime import datetime, timezone
from unittest.mock import patch

from amazon_scout.prospective_shadow_v14c2 import (
    FROZEN_MODEL, FUNNEL_CONFIG, V14C2_ESTIMATED_PHYSICAL_PROFILES,
    _apply_v13_economics, collect_dataforseo, render_report,
    run_shadow_validation, select_deep_candidates, v14c2_settings,
)
from amazon_scout.economics_v13 import calculate_candidate_economics
from amazon_scout.scoring_calibration_v14c import (
    COMPETITION_WEIGHTS, DEMAND_WEIGHTS, PROPOSED_OPPORTUNITY_WEIGHTS, load_artifacts,
)
from amazon_scout.sources.dataforseo import DataForSEOCache, DataForSEOMode, DataForSEOSettings, DataForSEOSource, ENDPOINTS, EvidenceEnvironment


def fixture(count=6):
    source=load_artifacts()["v13"]; rows=copy.deepcopy(source["analyses"][:count])
    return {"research_run":{"marketplace":"amazon.ae","candidate_funnel":{"generated":60,"screened":25}},"analyses":rows}


def disable_dfs(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE","disabled"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","false")
    monkeypatch.setenv("DATAFORSEO_LOGIN","fixture"); monkeypatch.setenv("DATAFORSEO_PASSWORD","fixture")


def enable_dfs(monkeypatch,tasks="10",cost="0.15"):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","true")
    monkeypatch.setenv("DATAFORSEO_V14C2_MAX_TASKS",tasks); monkeypatch.setenv("DATAFORSEO_V14C2_MAX_COST_USD",cost)
    monkeypatch.setenv("DATAFORSEO_LOGIN","fixture"); monkeypatch.setenv("DATAFORSEO_PASSWORD","fixture")


class FakeSource:
    def __init__(self,cost=.01): self.calls=[]; self.cost=cost
    def request(self,endpoint,task,budget,cache,estimated_cost=0):
        self.calls.append((endpoint,task)); budget.authorize(EvidenceEnvironment.PRODUCTION,estimated_cost)
        if endpoint==ENDPOINTS["product_competitors"]: items=[{"asin":"B0COMP0001","intersections":2,"avg_position":8}]
        else: items=[{"keyword_data":{"keyword":"اختبار","keyword_info":{"search_volume":None}},"ranked_serp_element":{"serp_item":{"type":"organic","rank_absolute":4}}}]
        payload={"status_code":20000,"cost":self.cost,"tasks":[{"status_code":20000,"cost":self.cost,"data":task,"result":[{"items":items}]}]}; budget.record(payload,True); return payload,False


def test_v14c_formula_and_weights_are_frozen():
    assert FROZEN_MODEL["demand_weights"]==DEMAND_WEIGHTS
    assert FROZEN_MODEL["competition_weights"]==COMPETITION_WEIGHTS
    assert FROZEN_MODEL["opportunity_weights"]==PROPOSED_OPPORTUNITY_WEIGHTS


def test_dual_scoring_and_production_score_unchanged(monkeypatch):
    disable_dfs(monkeypatch); bundle=fixture(); original=[a["opportunity_score"] for a in bundle["analyses"]]
    result=run_shadow_validation(bundle,now=datetime(2026,8,14,tzinfo=timezone.utc))
    assert result["production_scores_changed"] is False and result["v14c_formula_frozen"]
    assert [r["current"]["opportunity_score"] for r in result["candidates"]]==original[:len(result["candidates"])]
    assert all("opportunity_score" in r["proposed"] and "opportunity_score" in r["current"] for r in result["candidates"])


def test_shadow_score_cannot_influence_research_selection():
    bundle=fixture()
    with patch("amazon_scout.prospective_shadow_v14c2.calibrate_candidate",side_effect=AssertionError("shadow called during selection")):
        selected=select_deep_candidates(bundle)
    assert selected and all(item["gates"]["price"]["gate"] for item in selected)


def test_bulk_volume_and_merchant_never_called_by_default(monkeypatch):
    disable_dfs(monkeypatch); source=FakeSource(); result=run_shadow_validation(fixture(),source=source,cache=object())
    assert source.calls==[] and result["bulk_search_volume_calls"]==0 and result["merchant_sellers_calls"]==0


def test_product_competitors_priority(monkeypatch):
    enable_dfs(monkeypatch); deep=select_deep_candidates(fixture(3)); source=FakeSource(); collect_dataforseo(deep,source=source,cache=object())
    endpoints=[endpoint for endpoint,_ in source.calls]
    first_ranked=endpoints.index(ENDPOINTS["ranked_keywords"])
    assert all(endpoint==ENDPOINTS["product_competitors"] for endpoint in endpoints[:first_ranked])
    assert ENDPOINTS["bulk_search_volume"] not in endpoints and ENDPOINTS["merchant_sellers"] not in endpoints


def test_dataforseo_cost_and_task_guards(monkeypatch):
    enable_dfs(monkeypatch,tasks="99",cost="9"); settings=v14c2_settings(); assert settings.max_tasks_per_run==10 and settings.max_cost_usd_per_run==.15
    enable_dfs(monkeypatch,tasks="2",cost="0.15"); source=FakeSource(); _,usage,_=collect_dataforseo(select_deep_candidates(fixture(4)),source=source,cache=object())
    assert usage["tasks_attempted"]==2 and usage["provider_reported_cost"]<=.15
    enable_dfs(monkeypatch,tasks="10",cost="0.03"); source=FakeSource(); _,usage,_=collect_dataforseo(select_deep_candidates(fixture(4)),source=source,cache=object())
    assert usage["provider_reported_cost"]<=.03 and usage["tasks_attempted"]<=2


class HTTPResponse:
    status=200; headers={}
    def __init__(self,payload): self.data=json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.data


def test_cache_reuse_avoids_repeat_billing(monkeypatch,tmp_path):
    enable_dfs(monkeypatch); deep=select_deep_candidates(fixture(2)); settings=DataForSEOSettings(DataForSEOMode.PRODUCTION,True,.15,10,"login","password"); source=DataForSEOSource(settings); cache=DataForSEOCache(tmp_path)
    def response(request,timeout=30):
        task=json.loads(request.data)[0]; endpoint=ENDPOINTS["product_competitors"] if request.full_url.endswith(ENDPOINTS["product_competitors"]) else ENDPOINTS["ranked_keywords"]
        items=[{"asin":"B0COMP0001","intersections":2,"avg_position":8}] if endpoint==ENDPOINTS["product_competitors"] else [{"keyword_data":{"keyword":"x","keyword_info":{}},"ranked_serp_element":{"serp_item":{"type":"organic","rank_absolute":3}}}]
        return HTTPResponse({"status_code":20000,"cost":.01,"tasks":[{"status_code":20000,"cost":.01,"data":task,"result":[{"items":items}]}]})
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",side_effect=response) as transport:
        _,first,_=collect_dataforseo(deep,source=source,cache=cache); _,second,_=collect_dataforseo(deep,source=source,cache=cache)
    assert transport.call_count==first["tasks_attempted"] and first["provider_reported_cost"]>0
    assert second["provider_reported_cost"]==0 and second["cache_hits"]==transport.call_count


def test_confidence_tiers_and_unknown_risk_block_strong(monkeypatch):
    disable_dfs(monkeypatch); result=run_shadow_validation(fixture())
    for row in result["candidates"]:
        tier=row["shadow_tier"]["maximum_tier"]; confidence=row["proposed"]["overall_evidence_confidence"]
        if confidence<55: assert tier=="PRELIMINARY_NEEDS_EVIDENCE"
        if row["current_risk_status"]=="UNKNOWN": assert tier!="STRONG_ELIGIBLE"


def test_low_confidence_partial_economics_cannot_create_strong(monkeypatch):
    disable_dfs(monkeypatch); bundle=fixture(1); analysis=bundle["analyses"][0]; analysis["economics"]["status"]="PARTIAL"; analysis["economics"]["confidence"]=45
    result=run_shadow_validation(bundle); assert result["candidates"][0]["shadow_tier"]["maximum_tier"]!="STRONG_ELIGIBLE"


def test_missing_data_reward_and_economics_arithmetic(monkeypatch):
    disable_dfs(monkeypatch); result=run_shadow_validation(fixture())
    for row in result["candidates"]:
        arithmetic=row["proposed"]["opportunity_arithmetic"]["arithmetic"]
        assert all(item["contribution"]==0 for item in arithmetic if item["score"] is None)
        assert round(sum(item["contribution"] for item in arithmetic),2)==row["proposed"]["opportunity_score"]
        econ=next(item for item in arithmetic if item["component"]=="economics")
        expected=0 if econ["score"] is None else round(econ["score"]*.35,4); assert econ["contribution"]==expected


def test_deterministic_results_and_funnel_consistency(monkeypatch):
    disable_dfs(monkeypatch); bundle=fixture(); now=datetime(2026,8,14,tzinfo=timezone.utc); first=run_shadow_validation(bundle,now=now); second=run_shadow_validation(bundle,now=now)
    assert first==second and first["funnel_configuration"]==FUNNEL_CONFIG
    f=first["funnel"]; assert f["generated"]>=f["screened"]>=f["amazon_validated"]>=f["deep_validated"]
    assert f["deep_validated"]==len(first["candidates"]) and f["dataforseo_validated"]<=f["deep_validated"] and f["economics_validated"]<=f["deep_validated"]
    assert first["acceptance"]["recommendation"] in {"READY_FOR_V14D","NEEDS_MINOR_CALIBRATION","NOT_READY"}
    assert first["acceptance"]["checks"]["arithmetic_reconciles"]


def test_max_landed_cost_is_preserved(monkeypatch):
    disable_dfs(monkeypatch); bundle=fixture(1); analysis=bundle["analyses"][0]; expected=analysis["economics"]["scenarios"]["BASE"]["maximum_landed_cost_aed"]["25"]
    result=run_shadow_validation(bundle); assert result["candidates"][0]["economics_detail"]["max_landed_cost_25_aed"]==expected


def frozen_prospective_bundle():
    return json.loads(__import__('pathlib').Path("research/normalized/2026-08-14-045804-v1.4c2-prospective-evidence-bundle.json").read_text(encoding="utf-8"))


def test_v13_economics_invoked_for_frozen_deep_finalists_and_persisted(monkeypatch):
    disable_dfs(monkeypatch); bundle=frozen_prospective_bundle(); frozen=list(bundle["deep_finalists"])
    with patch("amazon_scout.prospective_shadow_v14c2.calculate_candidate_economics",wraps=calculate_candidate_economics) as engine:
        result=run_shadow_validation(bundle,now=datetime(2026,8,14,tzinfo=timezone.utc))
    assert engine.call_count==5 and result["selection_snapshot"]==frozen
    assert result["funnel"]["economics_validated"]==5
    assert all(row["economics_detail"]["economics_score"] is not None for row in result["candidates"])
    assert all(row["economics_detail"]["max_landed_cost_25_aed"] is not None for row in result["candidates"])


def test_estimated_profiles_remain_explicit_and_partial():
    bundle=frozen_prospective_bundle()
    for analysis in select_deep_candidates(bundle):
        enriched=_apply_v13_economics(analysis); economics=enriched["economics"]
        assert economics["physical_profile"]["source"]=="ESTIMATED"
        assert economics["status"]=="PARTIAL" and economics["confidence"]<75
        assert economics["score"]["raw"] is not None


def test_insufficient_economics_remains_insufficient_without_price_or_profile():
    analysis={"niche":"unmapped prospective niche","fee_calculation_price_aed":99,"economics":{"status":"INSUFFICIENT","confidence":20,"score":{"raw":None}}}
    assert _apply_v13_economics(analysis)["economics"]==analysis["economics"]
    no_price={"niche":"watch organizer box with drawer","fee_calculation_price_aed":None,"economics":{"status":"INSUFFICIENT","confidence":20,"score":{"raw":None}}}
    assert _apply_v13_economics(no_price)["economics"]==no_price["economics"]


def test_v13_formula_output_is_unchanged_when_called_directly():
    before=calculate_candidate_economics("long handle baseboard cleaning tool",100)
    after=calculate_candidate_economics("long handle baseboard cleaning tool",100)
    assert before==after and before["fee_rule_version"]=="amazon-ae-v1.3-2025-08-01"


def test_frozen_run_has_no_discovery_or_dataforseo_and_current_scores_unchanged(monkeypatch):
    disable_dfs(monkeypatch); bundle=frozen_prospective_bundle(); current={x["niche"]:x["opportunity_score"] for x in bundle["analyses"]}
    with patch("amazon_scout.prospective_shadow_v14c2.DataForSEOSource.request",side_effect=AssertionError("DataForSEO forbidden")) as dfs:
        result=run_shadow_validation(bundle)
    assert dfs.call_count==0 and result["dataforseo_usage"]["tasks_attempted"]==0
    assert result["selection_snapshot"]==bundle["deep_finalists"]
    assert all(row["current"]["opportunity_score"]==current[row["candidate"]] for row in result["candidates"])


def test_funnel_report_uses_collector_cheap_screen_count(monkeypatch):
    disable_dfs(monkeypatch); result=run_shadow_validation(frozen_prospective_bundle())
    report=render_report(result)
    assert "Funnel — generated 64; screened 64;" in report
