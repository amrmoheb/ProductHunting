import copy

from amazon_scout.economics_v13 import calculate_candidate_economics
from amazon_scout.production_scoring_v14d import (
    COMPETITION_WEIGHTS, DATAFORSEO_ROLES, DEMAND_WEIGHTS,
    PROPOSED_OPPORTUNITY_WEIGHTS, SCORING_VERSION, eligibility_tier,
    score_analysis,
)
from amazon_scout.scoring_calibration_v14c import load_artifacts


def analysis():
    return copy.deepcopy(load_artifacts()["v13"]["analyses"][0])


def test_exact_active_weights_and_version():
    assert SCORING_VERSION == "V1.4D"
    assert DEMAND_WEIGHTS == {"listing_activity": .35, "review_activity": .30, "search_evidence": .20, "breadth_freshness": .15}
    assert COMPETITION_WEIGHTS == {"comparable_density": .30, "review_barrier": .25, "market_concentration": .15, "dataforseo_competitors": .20, "dataforseo_ranked_keywords": .10}
    assert PROPOSED_OPPORTUNITY_WEIGHTS == {"demand": .30, "competition": .25, "economics": .35, "risk": .10}


def test_production_arithmetic_reconciles_and_confidence_is_separate():
    result = score_analysis(analysis())
    arithmetic = result["score_breakdown"]["arithmetic"]
    assert round(sum(row["contribution"] for row in arithmetic), 2) == result["opportunity_score"]
    assert result["score_breakdown"]["confidence_adjustment"]["multiplier"] == 1.0
    assert result["scoring_version"] == "V1.4D"


def test_missing_evidence_does_not_improve_score_and_null_is_not_zero():
    baseline = score_analysis(analysis())
    changed = analysis(); changed["economics"] = {"status": "UNKNOWN", "confidence": 0, "score": {"raw": None}}
    missing = score_analysis(changed)
    row = next(x for x in missing["score_breakdown"]["arithmetic"] if x["component"] == "economics")
    assert row["score"] is None and row["contribution"] == 0
    assert missing["opportunity_score"] <= baseline["opportunity_score"]


def test_confidence_caps_and_strong_blockers():
    assert eligibility_tier(80, 54.99, "SUFFICIENT", "SUFFICIENT", 80, gates_pass=True)["maximum_tier"] == "PRELIMINARY_NEEDS_EVIDENCE"
    assert eligibility_tier(80, 60, "SUFFICIENT", "SUFFICIENT", 80, gates_pass=True)["maximum_tier"] == "VALIDATED"
    assert eligibility_tier(80, 75, "UNKNOWN", "SUFFICIENT", 80, gates_pass=True)["maximum_tier"] == "VALIDATED"
    assert eligibility_tier(80, 75, "SUFFICIENT", "PARTIAL", 40, gates_pass=True)["maximum_tier"] == "VALIDATED"
    assert eligibility_tier(80, 75, "SUFFICIENT", "SUFFICIENT", 80, gates_pass=True)["maximum_tier"] == "STRONG_ELIGIBLE"


def test_v13_economics_output_is_unchanged():
    before = calculate_candidate_economics("long handle baseboard cleaning tool", 100)
    score_analysis(analysis())
    after = calculate_candidate_economics("long handle baseboard cleaning tool", 100)
    assert before == after


def test_dataforseo_is_optional_and_roles_are_explicit(monkeypatch):
    monkeypatch.setattr("amazon_scout.sources.dataforseo.DataForSEOSource.request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("provider call forbidden")))
    result = score_analysis(analysis())
    assert result["dataforseo_roles"] == DATAFORSEO_ROLES
    assert result["v14d_competition"]["families"]["dataforseo_competitors"]["score"] is None
    assert DATAFORSEO_ROLES["amazon_labs_en"] == "NOT_CONFIRMED"
