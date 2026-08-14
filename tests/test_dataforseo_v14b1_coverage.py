import json
from pathlib import Path
from unittest.mock import patch
import pytest

from amazon_scout.dataforseo_v14b import CANDIDATES, _safe_call, _volume_audit, load_inputs, render_report, run_poc, volume_status
from amazon_scout.dataforseo_v14b_coverage import *
from amazon_scout.sources.dataforseo import DataForSEOBudget, DataForSEOCache, DataForSEOMode, DataForSEOSettings, DataForSEOSource, ENDPOINTS, EvidenceEnvironment
from test_dataforseo_v14b import FakeSource, HTTPResponse

def enable_coverage(monkeypatch,cost="0.025",tasks="1"):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","true")
    monkeypatch.setenv("DATAFORSEO_V14B_COVERAGE_MAX_COST_USD",cost); monkeypatch.setenv("DATAFORSEO_V14B_COVERAGE_MAX_TASKS",tasks)
    monkeypatch.setenv("DATAFORSEO_LOGIN","login"); monkeypatch.setenv("DATAFORSEO_PASSWORD","password")

def test_null_zero_numeric_missing_distinction_and_no_misleading_count():
    rows={
      "أداة تنظيف حواف الجدران":{"search_volume":None,"search_volume_present":True},
      "ممسحة حواف الجدران":{"search_volume":0,"search_volume_present":True},
      "فرشاة تنظيف الوزرة":{"search_volume":12,"search_volume_present":True},
      "ممسحة جدران بمقبض طويل":{"search_volume_present":False},
    }
    audit=_volume_audit(CANDIDATES[0],rows)
    assert audit["numeric_volume_count"]==1 and audit["zero_volume_count"]==1
    assert audit["null_volume_count"]==1 and audit["missing_volume_count"]==1
    assert audit["median_keyword_volume"]==6 and audit["maximum_keyword_volume"]==12
    assert "non_zero_keyword_count" not in audit

def test_all_null_is_no_provider_data_and_report_has_no_nonzero_zero():
    rows={keyword:{"search_volume":None,"search_volume_present":True} for keyword in [x[1] for x in __import__("amazon_scout.dataforseo_v14b",fromlist=["ARABIC_KEYWORD_CLUSTERS"]).ARABIC_KEYWORD_CLUSTERS[CANDIDATES[0]]]}
    audit=_volume_audit(CANDIDATES[0],rows)
    assert audit["status"]=="NO_PROVIDER_VOLUME_DATA" and audit["median_keyword_volume"] is None and audit["maximum_keyword_volume"] is None
    assert audit["cluster_total"] is None and audit["null_volume_count"]==4

def test_competition_not_run_when_local_budget_skips(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","true"); monkeypatch.setenv("DATAFORSEO_V14B_MAX_COST_USD","0.20"); monkeypatch.setenv("DATAFORSEO_V14B_MAX_TASKS","1"); monkeypatch.setenv("DATAFORSEO_LOGIN","x"); monkeypatch.setenv("DATAFORSEO_PASSWORD","y")
    raw,norm=load_inputs(); bundle=run_poc(source=FakeSource(),cache=object(),raw=raw,normalized=norm)
    assert all(c["dataforseo_audit"]["competition_evidence"]=="NOT_RUN" for c in bundle["candidates"])
    report=render_report(bundle); assert "0 competitor rows" not in report and "NOT_RUN" in report

def test_skipped_endpoint_classification():
    settings=DataForSEOSettings(DataForSEOMode.PRODUCTION,True,.025,0,"x","y"); budget=DataForSEOBudget.from_settings(settings); outcomes=[]
    assert _safe_call(object(),ENDPOINTS["product_competitors"],{},budget,object(),lambda *_:[],outcomes) is None
    assert outcomes==[{"endpoint":ENDPOINTS["product_competitors"],"status":"SKIPPED_LOCAL_TASK_BUDGET"}]

def test_control_and_exact_six_keyword_task_uae_ar():
    assert CONTROL_KEYWORD=="حقيبة سفر"
    assert COVERAGE_KEYWORDS==["حقيبة سفر","كروشيه","مروحة سقف","مسند قدم","تنظيف الجدران","لوح تمارين"]
    assert coverage_task()=={"keywords":COVERAGE_KEYWORDS,"location_code":2784,"language_code":"ar"}

class CoverageSource:
    def __init__(self): self.calls=[]
    def request(self,endpoint,task,budget,cache,estimated_cost=0):
        self.calls.append((endpoint,task)); budget.authorize(EvidenceEnvironment.PRODUCTION,estimated_cost)
        items=[{"keyword":keyword,"search_volume":None} for keyword in task["keywords"]]; result={"location_code":2784,"language_code":"ar","items":items}
        payload={"status_code":20000,"cost":.0144,"tasks":[{"status_code":20000,"cost":.0144,"data":task,"result":[result]}]}; budget.record(payload,True); return payload,False

def test_probe_one_bulk_task_only_and_no_scoring_changes(monkeypatch):
    enable_coverage(monkeypatch); source=CoverageSource(); bundle=run_coverage_probe(source=source,cache=object())
    assert source.calls==[(ENDPOINTS["bulk_search_volume"],coverage_task())]
    assert bundle["official_scores_changed"] is False and bundle["ranked_keywords_calls"]==0 and bundle["product_competitors_calls"]==0
    assert bundle["interpretation"]=="ARABIC_AMAZON_UAE_VOLUME_COVERAGE_NOT_USEFUL_FOR_PRODUCT_HUNTING_DEMAND_MODEL"
    assert bundle["provider_usage"]["tasks_attempted"]==1 and bundle["provider_usage"]["provider_reported_cost"]==.0144

def test_probe_cost_and_task_guards_hard_capped(monkeypatch):
    enable_coverage(monkeypatch,cost="9",tasks="99"); settings=coverage_settings(); assert settings.max_tasks_per_run==1 and settings.max_cost_usd_per_run==.025
    monkeypatch.setenv("DATAFORSEO_V14B_COVERAGE_MAX_COST_USD","0");
    with pytest.raises(PermissionError): run_coverage_probe(source=CoverageSource(),cache=object())

def test_normalized_keyword_rows_persisted(monkeypatch,tmp_path):
    enable_coverage(monkeypatch); bundle=run_coverage_probe(source=CoverageSource(),cache=object()); _,evidence=write_coverage_outputs(bundle,tmp_path); saved=json.loads(evidence.read_text())
    assert len(saved["normalized_keyword_rows"])==6
    required={"candidate","keyword","search_volume","volume_status","provider","location_code","language_code","environment"}
    assert all(required<=set(row) for row in saved["normalized_keyword_rows"])
    assert all(row["volume_status"]=="NULL_PROVIDER_VOLUME" for row in saved["normalized_keyword_rows"])

def test_cached_rerun_avoids_billing(monkeypatch,tmp_path):
    enable_coverage(monkeypatch); settings=coverage_settings(); source=DataForSEOSource(settings); cache=DataForSEOCache(tmp_path); task=coverage_task()
    result={"location_code":2784,"language_code":"ar","items":[{"keyword":k,"search_volume":None} for k in COVERAGE_KEYWORDS]}; payload={"status_code":20000,"cost":.0144,"tasks":[{"status_code":20000,"cost":.0144,"data":task,"result":[result]}]}
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=HTTPResponse(payload)) as transport:
        first=run_coverage_probe(source=source,cache=cache); second=run_coverage_probe(source=source,cache=cache)
    assert transport.call_count==1 and first["provider_usage"]["provider_reported_cost"]==.0144
    assert second["provider_usage"]["provider_reported_cost"]==0 and second["provider_usage"]["cache_hits"]==1

def test_default_probe_refuses_without_paid_opt_in(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","false")
    with pytest.raises(PermissionError): run_coverage_probe(source=CoverageSource(),cache=object())
