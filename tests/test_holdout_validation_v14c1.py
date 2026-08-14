import copy
from datetime import datetime, timezone
from unittest.mock import patch

from amazon_scout.holdout_validation_v14c1 import (
    BASE_WEIGHTS,
    SELECTION_RULE,
    SENSITIVITY_WEIGHTS,
    _distribution,
    economics_dominance_risk,
    run_holdout_validation,
    select_holdout,
    spearman,
    write_outputs,
)
from amazon_scout.scoring_calibration_v14c import CANDIDATES, calibrate_candidate, load_artifacts, weighted_score


def artifacts(): return load_artifacts()


def test_calibration_five_are_excluded_and_holdout_is_deterministic():
    data=artifacts(); first=select_holdout(data["v13"]); second=select_holdout(data["v13"])
    assert [row["niche"] for row in first]==[row["niche"] for row in second]
    assert not set(CANDIDATES).intersection(row["niche"] for row in first)
    assert len(first)==13 and "Preserve V1.3 artifact order" in SELECTION_RULE


def test_no_network_or_paid_provider_calls():
    with patch("urllib.request.urlopen",side_effect=AssertionError("network forbidden")) as transport:
        bundle=run_holdout_validation(artifacts=artifacts(),now=datetime(2026,8,14,tzinfo=timezone.utc))
    assert transport.call_count==0 and bundle["provider_calls"]==0 and bundle["paid_calls"]==0


def test_missing_evidence_never_rewards_score():
    weights={"observed":.5,"missing":.5}
    full=weighted_score({"observed":{"score":60,"status":"OBSERVED_POSITIVE"},"missing":{"score":80,"status":"OBSERVED_POSITIVE"}},weights)
    missing=weighted_score({"observed":{"score":60,"status":"OBSERVED_POSITIVE"},"missing":{"score":None,"status":"UNKNOWN"}},weights)
    assert missing["score"]<full["score"] and missing["arithmetic"][1]["contribution"]==0
    assert run_holdout_validation(artifacts=artifacts())["failure_mode_checks"]["missing_data_reward"]["pass"]


def test_demand_saturation_detection():
    clustered=_distribution([86.25]*13); separated=_distribution([40+i for i in range(13)])
    assert clustered["suspicious_clustering"] and clustered["unique_rounded_score_count"]==1
    assert not separated["suspicious_clustering"]
    check=run_holdout_validation(artifacts=artifacts())["failure_mode_checks"]["demand_saturation"]
    assert check["materially_reduced"] is True


def test_economics_dominance_detection():
    assert economics_dominance_risk(70,30,45)
    assert not economics_dominance_risk(70,20,45)
    assert not economics_dominance_risk(70,30,70)
    bundle=run_holdout_validation(artifacts=artifacts())
    assert bundle["failure_mode_checks"]["economics_dominance"]["pass"]
    assert all(row["economics_contribution"]==0 for row in bundle["candidates"])


def test_competition_direction_is_not_inverted():
    bundle=run_holdout_validation(artifacts=artifacts())
    assert bundle["failure_mode_checks"]["competition_inversion"]["pass"]
    pairs=sorted((row["proposed"]["competition_evidence_breakdown"]["comparable_density"]["facts"]["unique_comparable_asins"],row["proposed"]["competition_evidence_breakdown"]["comparable_density"]["score"]) for row in bundle["candidates"])
    for (count_a,score_a),(count_b,score_b) in zip(pairs,pairs[1:]):
        if count_b>count_a: assert score_b<=score_a


def test_confidence_is_independent_from_raw_score():
    data=artifacts(); analysis=select_holdout(data["v13"])[0]; changed=copy.deepcopy(analysis); changed["data_confidence_score"]=0
    first=calibrate_candidate(analysis,data["v14b1"],data["v14b2"]); second=calibrate_candidate(changed,data["v14b1"],data["v14b2"])
    assert first["proposed"]["demand_score"]==second["proposed"]["demand_score"]
    assert first["proposed"]["competition_score"]==second["proposed"]["competition_score"]
    assert first["proposed"]["opportunity_score"]==second["proposed"]["opportunity_score"]
    assert run_holdout_validation(artifacts=data)["failure_mode_checks"]["confidence_leakage"]["pass"]


def test_ranking_metrics_with_known_order_and_holdout_movements():
    assert spearman({"a":3,"b":2,"c":1},{"a":3,"b":2,"c":1})==1
    assert spearman({"a":3,"b":2,"c":1},{"a":1,"b":2,"c":3})==-1
    movement=run_holdout_validation(artifacts=artifacts())["ranking_movement"]
    assert movement["spearman_rank_correlation"] is not None
    assert movement["maximum_rank_movement"]>=movement["median_rank_movement"]
    assert all("explanation" in row for row in movement["candidates_moving_at_least_5"])


def test_frozen_economics_sensitivity_scenarios():
    bundle=run_holdout_validation(artifacts=artifacts())
    assert bundle["weights_frozen"]==BASE_WEIGHTS=={"demand":.30,"competition":.25,"economics":.35,"risk":.10}
    assert set(bundle["economics_sensitivity_scenarios"])==set(SENSITIVITY_WEIGHTS)=={"SCENARIO_A","SCENARIO_B"}
    assert SENSITIVITY_WEIGHTS["SCENARIO_A"]=={"demand":.30,"competition":.30,"economics":.30,"risk":.10}
    assert SENSITIVITY_WEIGHTS["SCENARIO_B"]=={"demand":.35,"competition":.30,"economics":.25,"risk":.10}


def test_production_scores_and_v13_economics_unchanged():
    data=artifacts(); originals={row["niche"]:row for row in data["v13"]["analyses"]}; bundle=run_holdout_validation(artifacts=data)
    assert bundle["production_scores_changed"] is False
    for row in bundle["candidates"]:
        original=originals[row["candidate"]]
        assert row["current"]["opportunity_score"]==original["opportunity_score"]
        assert row["economics"]==original["economics"]


def test_deterministic_repeated_run_and_output_names(tmp_path):
    data=artifacts(); now=datetime(2026,8,14,tzinfo=timezone.utc)
    first=run_holdout_validation(artifacts=data,now=now); second=run_holdout_validation(artifacts=data,now=now)
    assert first==second
    markdown,evidence=write_outputs(first,tmp_path)
    assert markdown.name.endswith("-v1.4c1-holdout-validation.md")
    assert evidence.name.endswith("-v1.4c1-holdout-validation.json")


def test_confidence_tier_policy_is_a_separate_unactivated_gate():
    bundle=run_holdout_validation(artifacts=artifacts()); policy=bundle["confidence_tier_policy"]
    assert "never multiply" in policy["confidence_application"]
    assert policy["unknown_risk"]=="cannot become STRONG"
    assert all(row["eligibility_policy_result"]["maximum_tier"]=="PRELIMINARY_NEEDS_EVIDENCE" for row in bundle["candidates"])
    assert bundle["activation_assessment"]["recommendation"]=="NOT_READY"
