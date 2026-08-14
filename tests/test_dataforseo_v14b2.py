import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from amazon_scout.dataforseo_v14b2 import (
    CANDIDATE,
    LANGUAGE_CODE,
    LOCATION_CODE,
    MAX_COST_USD,
    MAX_TASKS,
    TARGET_ASIN,
    poc_settings,
    product_competitors_task,
    ranked_keywords_task,
    render_report,
    run_poc,
    write_outputs,
)
from amazon_scout.sources.dataforseo import (
    ENDPOINTS,
    DataForSEOCache,
    DataForSEOMode,
    DataForSEOProviderError,
    DataForSEOSettings,
    DataForSEOSource,
    EvidenceEnvironment,
)


def enable(monkeypatch, *, tasks="2", cost="0.05"):
    monkeypatch.setenv("DATAFORSEO_MODE", "production")
    monkeypatch.setenv("DATAFORSEO_ALLOW_PAID", "true")
    monkeypatch.setenv("DATAFORSEO_V14B2_MAX_TASKS", tasks)
    monkeypatch.setenv("DATAFORSEO_V14B2_MAX_COST_USD", cost)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "fixture-login")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "fixture-password")


class FakeSource:
    def __init__(self, *, cost=.01, unsupported=None):
        self.cost = cost
        self.unsupported = unsupported
        self.calls = []

    def request(self, endpoint, task, budget, cache, estimated_cost=0):
        self.calls.append((endpoint, task))
        budget.authorize(EvidenceEnvironment.PRODUCTION, estimated_cost)
        if endpoint == self.unsupported:
            budget.tasks_failed += 1
            raise DataForSEOProviderError(50304, "Function unavailable", 0, {})
        if endpoint == ENDPOINTS["ranked_keywords"]:
            items = [{
                "keyword_data": {"keyword": "لوح كروشيه", "keyword_info": {"search_volume": None}},
                "ranked_serp_element": {"serp_item": {"type": "organic", "rank_absolute": 4}},
            }]
        else:
            items = [{
                "asin": "B0COMP0001", "intersections": 3, "avg_position": 7,
                "organic": {"count": 2}, "paid": None, "metrics": {"search_volume": None},
            }]
        payload = {"status_code": 20000, "cost": self.cost, "tasks": [{
            "status_code": 20000, "cost": self.cost, "data": task, "result": [{"items": items}],
        }]}
        budget.record(payload, True)
        return payload, False


def test_exactly_one_candidate_and_exact_asin():
    assert CANDIDATE == "wood crochet blocking board"
    assert TARGET_ASIN == "B0C5WLFKDT"
    assert ranked_keywords_task()["asin"] == TARGET_ASIN
    assert product_competitors_task()["asin"] == TARGET_ASIN


def test_only_two_allowed_tasks_uae_ar_and_no_forbidden_calls(monkeypatch):
    enable(monkeypatch)
    source = FakeSource()
    bundle = run_poc(source=source, cache=object(), now=datetime(2026, 8, 14, tzinfo=timezone.utc))
    assert [endpoint for endpoint, _ in source.calls] == [ENDPOINTS["ranked_keywords"], ENDPOINTS["product_competitors"]]
    assert all(task["asin"] == TARGET_ASIN and task["location_code"] == 2784 and task["language_code"] == "ar" for _, task in source.calls)
    assert all(task["limit"] <= 10 for _, task in source.calls)
    forbidden = {ENDPOINTS["bulk_search_volume"], ENDPOINTS["merchant_sellers"]}
    assert not forbidden.intersection(endpoint for endpoint, _ in source.calls)
    assert bundle["bulk_search_volume_calls"] == bundle["merchant_sellers_calls"] == 0
    assert bundle["related_keywords_calls"] == bundle["keyword_intersection_calls"] == 0


def test_task_and_cost_guards_are_hard_capped(monkeypatch):
    enable(monkeypatch, tasks="99", cost="9")
    settings = poc_settings()
    assert settings.max_tasks_per_run == MAX_TASKS == 2
    assert settings.max_cost_usd_per_run == MAX_COST_USD == .05
    enable(monkeypatch, tasks="1", cost="0.05")
    source = FakeSource()
    bundle = run_poc(source=source, cache=object())
    assert bundle["provider_usage"]["tasks_attempted"] == 1
    assert bundle["endpoint_outcomes"]["product_competitors"]["status"] == "SKIPPED_LOCAL_BUDGET"
    enable(monkeypatch, tasks="2", cost="0.025")
    source = FakeSource(cost=.01)
    bundle = run_poc(source=source, cache=object())
    assert bundle["provider_usage"]["tasks_attempted"] == 1
    assert bundle["endpoint_outcomes"]["product_competitors"]["status"] == "SKIPPED_LOCAL_BUDGET"
    assert bundle["provider_usage"]["provider_reported_cost"] <= .025


def test_unsupported_is_endpoint_specific(monkeypatch):
    enable(monkeypatch)
    bundle = run_poc(source=FakeSource(unsupported=ENDPOINTS["product_competitors"]), cache=object())
    assert bundle["ranked_keywords_conclusion"] == "SPARSE_BUT_USABLE"
    assert bundle["product_competitors_conclusion"] == "UNSUPPORTED"
    assert bundle["overall_conclusion"] == "DATAFORSEO_COMPETITION_LAYER_SUPPLEMENTAL"


def test_normalized_evidence_and_missing_values_not_fabricated(monkeypatch):
    enable(monkeypatch)
    bundle = run_poc(source=FakeSource(), cache=object())
    ranked = bundle["ranked_keywords"][0]
    assert ranked == {
        "target_asin": TARGET_ASIN, "keyword": "لوح كروشيه", "search_volume": None,
        "organic_position": 4, "paid_position": None,
        "ranking_metadata": {"serp_item": {"type": "organic", "rank_absolute": 4}},
        "language_code": LANGUAGE_CODE, "location_code": LOCATION_CODE,
        "provider": "dataforseo_amazon_labs", "environment": "PRODUCTION",
    }
    competitor = bundle["product_competitors"][0]
    assert competitor["target_asin"] == TARGET_ASIN and competitor["competitor_asin"] == "B0COMP0001"
    assert competitor["keyword_intersections"] == 3 and competitor["average_position"] == 7
    assert competitor["organic_visibility"] == {"count": 2} and competitor["paid_visibility"] is None
    assert competitor["search_volume_related_metrics"] == {"search_volume": None}


class HTTPResponse:
    status = 200
    headers = {}

    def __init__(self, payload):
        self.data = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.data


def test_cache_reuse_avoids_repeat_billing(monkeypatch, tmp_path):
    enable(monkeypatch)
    settings = DataForSEOSettings(DataForSEOMode.PRODUCTION, True, .05, 2, "login", "password")
    source = DataForSEOSource(settings)
    cache = DataForSEOCache(tmp_path)

    def response(request, timeout=30):
        task = json.loads(request.data)[0]
        if request.full_url.endswith(ENDPOINTS["ranked_keywords"]):
            items = [{"keyword_data": {"keyword": "كروشيه", "keyword_info": {}}, "ranked_serp_element": {"serp_item": {"type": "organic", "rank_absolute": 2}}}]
        else:
            items = [{"asin": "B0COMP0001", "intersections": 2, "avg_position": 5}]
        return HTTPResponse({"status_code": 20000, "cost": .01, "tasks": [{"status_code": 20000, "cost": .01, "data": task, "result": [{"items": items}]}]})

    with patch("amazon_scout.sources.dataforseo.urllib.request.urlopen", side_effect=response) as transport:
        first = run_poc(source=source, cache=cache)
        second = run_poc(source=source, cache=cache)
    assert transport.call_count == 2
    assert first["provider_usage"]["provider_reported_cost"] == .02
    assert second["provider_usage"]["provider_reported_cost"] == 0
    assert second["provider_usage"]["cache_hits"] == 2


def test_report_persistence_redaction_and_no_scoring_changes(monkeypatch, tmp_path):
    enable(monkeypatch)
    bundle = run_poc(source=FakeSource(), cache=object())
    markdown, evidence = write_outputs(bundle, tmp_path)
    combined = markdown.read_text() + evidence.read_text()
    assert bundle["official_scores_changed"] is False
    assert "Official scoring, gates, tiers, and V1.3 economics: UNCHANGED" in render_report(bundle)
    assert "fixture-login" not in combined and "fixture-password" not in combined and "Authorization" not in combined
    assert json.loads(evidence.read_text())["representative_asin"] == TARGET_ASIN


def test_default_refuses_and_automated_test_makes_no_provider_call(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_MODE", "production")
    monkeypatch.setenv("DATAFORSEO_ALLOW_PAID", "false")
    with pytest.raises(PermissionError):
        run_poc(source=FakeSource(), cache=object())
