import copy
import json
from datetime import datetime, timezone
from unittest.mock import patch

from amazon_scout.scoring_calibration_v14c import (
    CANDIDATES,
    COMPETITION_WEIGHTS,
    DEMAND_WEIGHTS,
    EVIDENCE_STATES,
    PROVIDER_ROLES,
    calibrate_candidate,
    competition_families,
    demand_families,
    load_artifacts,
    render_report,
    run_calibration,
    weighted_score,
)


def artifacts():
    return load_artifacts()


def analyses(bundle):
    return {row["niche"]: row for row in bundle["v13"]["analyses"] if row.get("niche") in CANDIDATES}


def test_offline_calibration_makes_no_network_or_paid_calls():
    with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")) as transport:
        bundle = run_calibration(artifacts=artifacts(), now=datetime(2026, 8, 14, tzinfo=timezone.utc))
    assert transport.call_count == 0
    assert bundle["provider_calls"] == bundle["paid_calls"] == 0


def test_null_is_not_zero_and_arabic_cannot_dominate_demand():
    data = artifacts(); by_name = analyses(data)
    null_families, _ = demand_families(by_name["adjustable airplane foot hammock"], data["v14b1"])
    numeric_families, _ = demand_families(by_name["wood crochet blocking board"], data["v14b1"])
    assert null_families["search_evidence"]["facts"]["arabic_volume_status"] == "NULL_PROVIDER_VOLUME"
    assert null_families["search_evidence"]["facts"]["arabic_subscore"] is None
    assert numeric_families["search_evidence"]["facts"]["arabic_volume_status"] == "NUMERIC_VOLUME"
    assert numeric_families["search_evidence"]["facts"]["arabic_weight_within_family"] == .10
    assert DEMAND_WEIGHTS["search_evidence"] == .20  # Arabic maximum is 2 points of total demand.


def test_unknown_never_rewards_and_missing_reduces_confidence():
    observed = {"a": {"score": 60, "status": "OBSERVED_POSITIVE"}, "b": {"score": 60, "status": "OBSERVED_POSITIVE"}}
    missing = copy.deepcopy(observed); missing["b"] = {"score": None, "status": "UNKNOWN"}
    full = weighted_score(observed, {"a": .5, "b": .5})
    partial = weighted_score(missing, {"a": .5, "b": .5})
    assert partial["score"] < full["score"] and partial["available_weight"] < full["available_weight"]
    assert partial["arithmetic"][1]["contribution"] == 0
    assert partial["arithmetic"][1]["missing_behavior"] == "ZERO_CONTRIBUTION_NO_REDISTRIBUTION"


def test_coverage_aware_weighting_has_fixed_denominator_and_explainable_arithmetic():
    data = artifacts(); row = run_calibration(artifacts=data)["candidates"][0]["proposed"]
    demand = row["demand_arithmetic"]
    assert demand["denominator"] == 1 and "not redistributed" in demand["formula"]
    assert round(sum(item["contribution"] for item in demand["arithmetic"]), 2) == row["demand_score"]
    assert round(sum(item["contribution"] for item in row["competition_arithmetic"]["arithmetic"]), 2) == row["competition_score"]
    assert round(sum(item["contribution"] for item in row["opportunity_arithmetic"]["arithmetic"]), 2) == row["opportunity_score"]


def test_dataforseo_competitors_only_when_observed_and_ranked_is_supplemental():
    data = artifacts(); by_name = analyses(data)
    crochet, _ = competition_families(by_name["wood crochet blocking board"], data["v14b2"])
    other, _ = competition_families(by_name["long handle baseboard cleaning tool"], data["v14b2"])
    assert crochet["dataforseo_competitors"]["score"] is not None
    assert crochet["dataforseo_competitors"]["facts"]["unique_external_competitors"] == 9
    assert crochet["dataforseo_ranked_keywords"]["facts"]["keyword_rows"] == 3
    assert COMPETITION_WEIGHTS["dataforseo_ranked_keywords"] == .10
    assert other["dataforseo_competitors"]["status"] == "NOT_RUN" and other["dataforseo_competitors"]["score"] is None
    assert other["dataforseo_ranked_keywords"]["status"] == "NOT_RUN"


def test_duplicate_asins_do_not_inflate_competition():
    data = artifacts(); analysis = copy.deepcopy(analyses(data)["adjustable airplane foot hammock"])
    baseline, _ = competition_families(analysis, data["v14b2"])
    analysis["products"].append(copy.deepcopy(analysis["products"][0]))
    duplicate, _ = competition_families(analysis, data["v14b2"])
    assert duplicate["comparable_density"]["score"] == baseline["comparable_density"]["score"]
    assert duplicate["market_concentration"]["score"] == baseline["market_concentration"]["score"]
    assert duplicate["comparable_density"]["facts"]["duplicate_asins_removed"] == 1


def test_score_and_confidence_are_separate_and_states_explicit():
    bundle = run_calibration(artifacts=artifacts())
    assert set(EVIDENCE_STATES) == {"OBSERVED_POSITIVE", "OBSERVED_NEGATIVE", "UNKNOWN", "NOT_SUPPORTED", "NOT_RUN", "STALE"}
    assert all(row["proposed"]["demand_score"] != row["proposed"]["demand_confidence"] for row in bundle["candidates"])
    assert all(row["proposed"]["opportunity_score"] != row["proposed"]["overall_evidence_confidence"] for row in bundle["candidates"])


def test_five_candidate_backtest_is_deterministic_and_separates_demand():
    data = artifacts(); now = datetime(2026, 8, 14, tzinfo=timezone.utc)
    first = run_calibration(artifacts=data, now=now); second = run_calibration(artifacts=data, now=now)
    assert first == second and tuple(row["candidate"] for row in first["candidates"]) == CANDIDATES
    assert len({row["proposed"]["demand_score"] for row in first["candidates"]}) > 1
    assert all(row["current"]["demand_score"] == 86.25 for row in first["candidates"])


def test_sensitivity_runs_and_stability_is_deterministic():
    sensitivity = run_calibration(artifacts=artifacts())["sensitivity"]
    assert set(sensitivity["scenarios"]) == {"dataforseo_competition_removed", "arabic_search_volume_removed", "review_weight_minus_20pct", "review_weight_plus_20pct", "comparable_density_weight_minus_20pct", "comparable_density_weight_plus_20pct"}
    assert sensitivity["stability"] in {"STABLE", "UNSTABLE"}
    assert sensitivity["stability"] == ("STABLE" if sensitivity["maximum_rank_shift"] <= 1 else "UNSTABLE")


def test_official_scores_and_v13_economics_are_unchanged():
    data = artifacts(); source = analyses(data); bundle = run_calibration(artifacts=data)
    assert bundle["official_scores_changed"] is False and bundle["would_production_scoring_change"] == "NO — audit-only"
    for row in bundle["candidates"]:
        original = source[row["candidate"]]
        assert row["current"]["opportunity_score"] == original["opportunity_score"]
        assert row["economics"] == original["economics"]
        assert row["official_scores_unchanged"] is True


def test_roles_and_report_disclose_limits_and_no_production_change():
    bundle = run_calibration(artifacts=artifacts())
    assert PROVIDER_ROLES["dataforseo_bulk_search_volume"]["role"] == "SUPPLEMENTAL_ONLY"
    assert PROVIDER_ROLES["dataforseo_product_competitors"]["poc_rows"] == 10
    assert PROVIDER_ROLES["dataforseo_ranked_keywords"]["poc_rows"] == 3
    assert bundle["DATAFORSEO_AMAZON_UAE_ENGLISH_COVERAGE"] == "NOT_CONFIRMED"
    assert bundle["DATAFORSEO_AMAZON_UAE_ARABIC_COVERAGE"] == "PARTIAL"
    report = render_report(bundle)
    assert "Would production scoring change? **NO — audit-only**" in report
    assert "Provider calls: 0; paid calls: 0" in report


def test_output_filename_preserves_v14c(tmp_path):
    from amazon_scout.scoring_calibration_v14c import write_outputs
    markdown, evidence = write_outputs(run_calibration(artifacts=artifacts()), tmp_path)
    assert markdown.name.endswith("-v1.4c-scoring-calibration.md")
    assert evidence.name.endswith("-v1.4c-scoring-calibration.json")
