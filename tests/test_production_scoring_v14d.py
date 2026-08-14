import copy

from amazon_scout.economics_v13 import calculate_candidate_economics, required_economics_raw, score_with_economics
from amazon_scout.production_scoring_v14d import (
    COMPETITION_WEIGHTS, DATAFORSEO_ROLES, DEMAND_WEIGHTS,
    PROPOSED_OPPORTUNITY_WEIGHTS, SCORING_VERSION, eligibility_tier,
    score_analysis,
)
from amazon_scout.scoring_calibration_v14c import load_artifacts
from amazon_scout.research_report import _economics_section


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


def test_report_uses_v14d_economics_weight_and_arithmetic():
    result=score_analysis(analysis()); result["niche"]="arbitrary future product"
    raw=result["economics"]["score"]["raw"]
    contribution=next(row["contribution"] for row in result["score_breakdown"]["arithmetic"] if row["component"]=="economics")
    report="\n".join(_economics_section([result]))
    assert "### arbitrary future product" in report
    assert "V1.4D economics opportunity weight: 35%" in report
    assert contribution==round(raw*.35,4)
    assert f"/ {contribution:.2f} /" in report


def test_report_passes_35_percent_to_legacy_helpers_without_changing_defaults():
    result=score_analysis(analysis()); report="\n".join(_economics_section([result]))
    raw=result["economics"]["score"]["raw"]; contribution=round(raw*.35,4)
    before=round(float(result["validated_opportunity_score"])-contribution,2)
    assert f"{required_economics_raw(before,55,weight=.35):.2f} / {required_economics_raw(before,65,weight=.35):.2f}" in report
    assert f"maximum score with economics raw 100: {score_with_economics(before,100,weight=.35):.2f}" in report
    assert required_economics_raw(46.55,55)==42.25
    assert score_with_economics(46.55,100)==66.55


def test_report_omits_unknown_economics_candidate():
    unknown={"niche":"unpriced future product","economics":{"status":"INSUFFICIENT","confidence":20,"score":{"raw":None},"scenarios":{}}}
    report="\n".join(_economics_section([unknown]))
    assert "unpriced future product" not in report
