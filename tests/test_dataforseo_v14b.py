import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import pytest

from amazon_scout.dataforseo_v14b import *
from amazon_scout.dataforseo_v14b import _volume_audit
from amazon_scout.sources.dataforseo import DataForSEOBudget, DataForSEOCache, DataForSEOSettings, DataForSEOMode, DataForSEOSource

class FakeSource:
    def __init__(self,cost=.01,unsupported=None): self.cost=cost; self.calls=[]; self.unsupported=unsupported
    def request(self,endpoint,task,budget,cache,estimated_cost=0):
        self.calls.append((endpoint,task)); budget.authorize(EvidenceEnvironment.PRODUCTION,estimated_cost)
        if endpoint==self.unsupported: budget.tasks_failed+=1; raise RuntimeError("unsupported")
        if endpoint==ENDPOINTS["bulk_search_volume"]:
            items=[{"keyword":k,"search_volume":i*10} for i,k in enumerate(task["keywords"],1)]
            result={"location_code":2784,"language_code":"ar","items":items}
        elif endpoint==ENDPOINTS["ranked_keywords"]:
            result={"items":[{"keyword_data":{"keyword":"اختبار","keyword_info":{"search_volume":10}},"ranked_serp_element":{"serp_item":{"type":"organic","rank_absolute":2}}}]}
        else:
            result={"items":[{"asin":"B0COMP0001","intersections":3,"avg_position":4,"organic":{"count":2},"paid":{"count":0},"metrics":{"search_volume":20}}]}
        payload={"status_code":20000,"cost":self.cost,"tasks":[{"status_code":20000,"cost":self.cost,"data":task,"result":[result]}]}; budget.record(payload,True); return payload,False

def inputs(): return load_inputs()

def enabled(monkeypatch,cost="0.20",tasks="12"):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","true"); monkeypatch.setenv("DATAFORSEO_V14B_MAX_COST_USD",cost); monkeypatch.setenv("DATAFORSEO_V14B_MAX_TASKS",tasks)
    monkeypatch.setenv("DATAFORSEO_LOGIN","fixture-login"); monkeypatch.setenv("DATAFORSEO_PASSWORD","fixture-password")

def test_five_candidate_mappings_and_clusters():
    raw,_=inputs(); mapping=representative_mapping(raw)
    assert tuple(mapping)==CANDIDATES and len(mapping)==5 and all(1<=len(v)<=3 for v in mapping.values())
    assert set(ARABIC_KEYWORD_CLUSTERS)==set(CANDIDATES) and all(3<=len(v)<=6 for v in ARABIC_KEYWORD_CLUSTERS.values())
    assert all(row["translation_research_provenance"] and row["keyword_intent"] for row in keyword_records())

def test_one_bulk_task_all_unique_arabic_keywords_uae_ar():
    task=bulk_task(); expected={row["arabic_keyword"] for row in keyword_records()}
    assert task["location_code"]==2784 and task["language_code"]=="ar" and set(task["keywords"])==expected and len(task["keywords"])==len(expected)

def test_cluster_total_unknown_not_summed():
    audit=_volume_audit(CANDIDATES[0],{row["arabic_keyword"]:{"search_volume":100,"search_volume_present":True} for row in keyword_records()})
    assert audit["cluster_total"] is None and audit["cluster_total_status"]=="UNKNOWN_OVERLAP_NOT_DEDUPLICATED"
    assert audit["median_keyword_volume"]==100 and audit["maximum_keyword_volume"]==100

def test_english_unconfirmed_and_partial_coverage():
    assert ENGLISH_COVERAGE=="NOT_CONFIRMED" and LANGUAGE_COVERAGE=="PARTIAL_AMAZON_UAE_LANGUAGE_COVERAGE"

def test_one_asin_per_candidate_initial_tasks_and_task_ceilings(monkeypatch):
    enabled(monkeypatch); raw,norm=inputs(); source=FakeSource(); bundle=run_poc(source=source,cache=object(),raw=raw,normalized=norm,now=datetime(2026,8,14,tzinfo=timezone.utc))
    ranked=[t for e,t in source.calls if e==ENDPOINTS["ranked_keywords"]]; competitors=[t for e,t in source.calls if e==ENDPOINTS["product_competitors"]]
    assert ranked==[] and competitors==[]
    assert bundle["provider_usage"]["tasks_attempted"]<=1 and len(source.calls)==1
    assert bundle["merchant_sellers_calls"]==0 and all(e!=ENDPOINTS["merchant_sellers"] for e,_ in source.calls)

def test_cost_ceiling_skips_lower_priority(monkeypatch):
    enabled(monkeypatch,cost="0.04",tasks="12"); raw,norm=inputs(); source=FakeSource(cost=.01); bundle=run_poc(source=source,cache=object(),raw=raw,normalized=norm)
    assert bundle["provider_usage"]["provider_reported_cost"]<=.04
    assert bundle["provider_usage"]["tasks_attempted"]==1

def test_task_ceiling(monkeypatch):
    enabled(monkeypatch,cost="0.20",tasks="2"); raw,norm=inputs(); source=FakeSource(); bundle=run_poc(source=source,cache=object(),raw=raw,normalized=norm)
    assert bundle["provider_usage"]["tasks_attempted"]==1 and len(source.calls)==1

def test_lower_priority_endpoints_not_run_and_no_rescore(monkeypatch):
    enabled(monkeypatch); raw,norm=inputs(); source=FakeSource(); bundle=run_poc(source=source,cache=object(),raw=raw,normalized=norm)
    assert sum(endpoint==ENDPOINTS["ranked_keywords"] for endpoint,_ in source.calls)==0
    assert sum(endpoint==ENDPOINTS["product_competitors"] for endpoint,_ in source.calls)==0
    assert bundle["official_scores_changed"] is False and all(c["official_scores_unchanged"] for c in bundle["candidates"])
    old={a["niche"]:a for a in norm["analyses"]}
    assert all(c["current_engine"]["demand_score"]==old[c["candidate"]]["demand_score"] for c in bundle["candidates"])

class HTTPResponse:
    status=200; headers={}
    def __init__(self,payload): self.data=json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return self.data

def test_cache_avoids_repeat_billing(tmp_path):
    settings=DataForSEOSettings(DataForSEOMode.PRODUCTION,True,.20,12,"login","password"); source=DataForSEOSource(settings); cache=DataForSEOCache(tmp_path); task=bulk_task()
    result={"location_code":2784,"language_code":"ar","items":[]}; payload={"status_code":20000,"cost":.01,"tasks":[{"status_code":20000,"cost":.01,"data":task,"result":[result]}]}
    first=DataForSEOBudget.from_settings(settings); second=DataForSEOBudget.from_settings(settings)
    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen",return_value=HTTPResponse(payload)) as transport:
        source.request(ENDPOINTS["bulk_search_volume"],task,first,cache,estimated_cost=.02); source.request(ENDPOINTS["bulk_search_volume"],task,second,cache,estimated_cost=.02)
    assert transport.call_count==1 and first.provider_reported_cost==.01 and second.provider_reported_cost==0 and second.cache_hits==1

def test_no_credentials_persisted_in_cache_or_report(tmp_path,monkeypatch):
    enabled(monkeypatch); raw,norm=inputs(); bundle=run_poc(source=FakeSource(),cache=object(),raw=raw,normalized=norm); md,js=write_outputs(bundle,tmp_path); text=md.read_text()+js.read_text()
    assert "fixture-login" not in text and "fixture-password" not in text and "Authorization" not in text

def test_report_arithmetic_cost_totals(monkeypatch):
    enabled(monkeypatch); raw,norm=inputs(); bundle=run_poc(source=FakeSource(cost=.01),cache=object(),raw=raw,normalized=norm); report=render_report(bundle)
    usage=bundle["provider_usage"]
    assert usage["provider_reported_cost"]==round(usage["tasks_succeeded"]*.01,8)
    assert usage["total_provider_reported_cost"]==usage["provider_reported_cost"]
    assert f"POC total provider cost: USD {usage['provider_reported_cost']:.8f}" in report and "Official opportunity scoring: UNCHANGED" in report

def test_default_command_refuses_paid_calls(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE","production"); monkeypatch.setenv("DATAFORSEO_ALLOW_PAID","false")
    with pytest.raises(PermissionError): run_poc(raw={},normalized={})
