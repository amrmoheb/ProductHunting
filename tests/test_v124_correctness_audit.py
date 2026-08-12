from __future__ import annotations

from datetime import datetime, timezone
import unittest

from amazon_scout.commercial_segments import evaluate_price_gate
from amazon_scout.evidence import EvidenceFreshness, EvidenceRecord, freshness_for
from amazon_scout.research_pipeline import canonical_products_by_asin, canonical_statistical_records
from amazon_scout.scoring import load_scoring_config, opportunity_score_breakdown, synthetic_ceiling_audit
from amazon_scout.sources.serpapi import classify_relevance

NOW=datetime(2026,8,12,4,0,tzinfo=timezone.utc); TS=NOW.isoformat()


def classified(niche: str, keyword: str, title: str):
    return classify_relevance({"asin":"B000000001","title":title},niche,keyword)


def record(identifier: str, asin: str, metric: str, value: float, observed: str=TS) -> EvidenceRecord:
    return EvidenceRecord.from_dict({"id":identifier,"metric_name":metric,"metric_value":value,"metric_unit":None,"asin":asin,"keyword":"k","niche":"n","marketplace":"amazon.ae","source_provider":"serpapi","source_type":"amazon_search","source_url":f"https://www.amazon.ae/dp/{asin}","source_title":"Amazon UAE","observed_at":observed,"retrieved_at":observed,"confidence":"HIGH","is_estimate":False,"market_relevance":"AMAZON_UAE","source_timezone":"UTC"},"r",validation_time=NOW)


def test_target_itself_is_accessory_not_excluded():
    result=classified("laptop riser","laptop riser","Foldable Laptop Stand")
    assert result["target_relationship"]=="TARGET_IS_ACCESSORY"


def test_accessory_to_target_is_excluded():
    result=classified("cable machine ankle strap","ankle strap cable machine","Replacement Carabiner Only for Ankle Strap")
    assert result["target_relationship"]=="ACCESSORY_TO_TARGET"


def test_laptop_riser_target_classification(): assert classified("foldable aluminum laptop riser","laptop riser foldable aluminum non powered","Foldable Aluminum Laptop Stand Adjustable")["target_match_quality"]=="EXACT_TARGET"
def test_ankle_strap_target_classification(): assert classified("padded cable machine ankle straps","ankle strap cable machine pair","Padded Ankle Straps for Cable Machine Pair")["target_relationship"]=="TARGET_IS_ACCESSORY"
def test_luggage_cup_holder_target_classification(): assert classified("luggage handle cup sling","luggage cup holder travel strap","Luggage Cup Holder Travel Sling")["target_relationship"]=="TARGET_IS_ACCESSORY"
def test_beach_towel_clip_target_classification(): assert classified("heavy duty beach towel clips","beach chair towel clips heavy duty","Heavy Duty Beach Chair Towel Clips")["target_relationship"]=="TARGET_IS_ACCESSORY"
def test_sweater_drying_rack_target_classification(): assert classified("stackable mesh sweater drying rack","sweater drying rack mesh stackable","Stackable Mesh Sweater Drying Rack")["target_relationship"]=="TARGET_IS_ACCESSORY"


def test_duplicate_asin_price_rows_count_once():
    rows=[record("p1","B000000001","current_price_aed",50),record("p2","B000000001","current_price_aed",90),record("p3","B000000002","current_price_aed",100)]
    assert len([r for r in canonical_statistical_records(rows) if r.metric_name=="current_price_aed"])==2


def test_duplicate_asin_reviews_count_once():
    rows=[record("r1","B000000001","review_count",10),record("r2","B000000001","review_count",20)]
    assert len(canonical_statistical_records(rows))==1


def test_duplicate_asin_cannot_bias_median():
    products=[{"asin":"A","current_price_aed":10},{"asin":"A","current_price_aed":10},{"asin":"A","current_price_aed":10},{"asin":"B","current_price_aed":90},{"asin":"C","current_price_aed":100}]
    canonical,_=canonical_products_by_asin(products); prices=[p["current_price_aed"] for p in canonical]
    assert sorted(prices)==[10,90,100]


def test_duplicate_asin_cannot_bias_in_band_ratio():
    products=[{"asin":"A","current_price_aed":10} for _ in range(8)]+[{"asin":"B","current_price_aed":60},{"asin":"C","current_price_aed":80}]
    canonical,_=canonical_products_by_asin(products); decision=evaluate_price_gate([p["current_price_aed"] for p in canonical],50,150,minimum_sample_size=1,minimum_in_target_band_ratio=.4)
    assert decision.in_target_band_ratio==2/3


def test_score_component_contributions_reproduce_final_exactly():
    weights=load_scoring_config()["weights"]; factors={name:73.0 for name in weights}; result=opportunity_score_breakdown(factors,weights,confidence=80)
    assert result["arithmetic_sum"]==result["final_pre_confidence_score"]==73.0


def test_perfect_candidate_mathematical_ceiling():
    result=synthetic_ceiling_audit(load_scoring_config()["weights"])["PERFECT_CANDIDATE"]
    assert result["final_pre_confidence_score"]==100.0


def test_very_good_candidate_score_fixture():
    result=synthetic_ceiling_audit(load_scoring_config()["weights"])["VERY_GOOD_CANDIDATE"]
    assert result["final_pre_confidence_score"]==83.5


def test_unknown_economics_behavior_is_zero_not_neutral():
    weights=load_scoring_config()["weights"]; factors={name:100.0 for name in weights}; factors["margin_potential"]=None
    result=opportunity_score_breakdown(factors,weights,confidence=100); margin=result["components"]["margin_potential"]
    assert margin["effective_raw"]==0 and margin["contribution"]==0 and margin["missing_evidence_behavior"]=="TREATED_AS_ZERO"
    assert result["final_pre_confidence_score"]==80.0


def test_static_regulatory_guidance_freshness_semantics():
    item=EvidenceRecord.from_dict({"id":"risk","metric_name":"regulatory_risk","metric_value":"MEDIUM","metric_unit":None,"asin":None,"keyword":None,"niche":"n","marketplace":"amazon.ae","source_provider":"uae_government","source_type":"official_government_web","source_url":"https://moiat.gov.ae/guidance","source_title":"Guidance","observed_at":TS,"retrieved_at":TS,"confidence":"HIGH","is_estimate":True,"market_relevance":"UAE_GENERAL","source_timezone":"UTC"},"r",validation_time=NOW)
    assert freshness_for(item,NOW)==EvidenceFreshness.STATIC_GUIDANCE


class V124CorrectnessAuditTests(unittest.TestCase):
    test_target_itself_is_accessory_not_excluded=lambda self: test_target_itself_is_accessory_not_excluded()
    test_accessory_to_target_is_excluded=lambda self: test_accessory_to_target_is_excluded()
    test_laptop_riser_target_classification=lambda self: test_laptop_riser_target_classification()
    test_ankle_strap_target_classification=lambda self: test_ankle_strap_target_classification()
    test_luggage_cup_holder_target_classification=lambda self: test_luggage_cup_holder_target_classification()
    test_beach_towel_clip_target_classification=lambda self: test_beach_towel_clip_target_classification()
    test_sweater_drying_rack_target_classification=lambda self: test_sweater_drying_rack_target_classification()
    test_duplicate_asin_price_rows_count_once=lambda self: test_duplicate_asin_price_rows_count_once()
    test_duplicate_asin_reviews_count_once=lambda self: test_duplicate_asin_reviews_count_once()
    test_duplicate_asin_cannot_bias_median=lambda self: test_duplicate_asin_cannot_bias_median()
    test_duplicate_asin_cannot_bias_in_band_ratio=lambda self: test_duplicate_asin_cannot_bias_in_band_ratio()
    test_score_component_contributions_reproduce_final_exactly=lambda self: test_score_component_contributions_reproduce_final_exactly()
    test_perfect_candidate_mathematical_ceiling=lambda self: test_perfect_candidate_mathematical_ceiling()
    test_very_good_candidate_score_fixture=lambda self: test_very_good_candidate_score_fixture()
    test_unknown_economics_behavior_is_zero_not_neutral=lambda self: test_unknown_economics_behavior_is_zero_not_neutral()
    test_static_regulatory_guidance_freshness_semantics=lambda self: test_static_regulatory_guidance_freshness_semantics()
