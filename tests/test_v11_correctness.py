from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from amazon_scout.evidence import EvidenceRecord, EvidenceFreshness, freshness_for, validate_bundle
from amazon_scout.research_pipeline import analyze_evidence_bundle, canonical_funnel, evidence_cutoff, source_status_from_evidence, validate_funnel_invariants
from amazon_scout.research_report import render_research_report

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def ev(identifier, metric, value, *, niche="test niche", relevance="AMAZON_UAE", provider="codex_web", source_type="indexed_amazon_search", observed=None, confidence="MEDIUM", unit=None, url="https://www.amazon.ae/s?k=test"):
    timestamp = (observed or NOW - timedelta(days=1)).isoformat()
    return EvidenceRecord.from_dict({"id":identifier,"metric_name":metric,"metric_value":value,"metric_unit":unit,"asin":None,"keyword":"test","niche":niche,"marketplace":"amazon.ae","market_relevance":relevance,"source_provider":provider,"source_type":source_type,"source_url":url,"source_title":"source","observed_at":timestamp,"retrieved_at":timestamp,"confidence":confidence,"is_estimate":False,"notes":None}, "run", validation_time=NOW)


def raw(products, *, price_min=50, price_max=150, funnel=None):
    return {"research_run":{"id":"run","slug":"v11","marketplace":"amazon.ae","started_at":NOW.isoformat(),"evidence_cutoff":NOW.isoformat(),"filters":{"price_min_aed":price_min,"price_max_aed":price_max},"candidate_funnel":funnel or {"generated":10,"screened":5}},"keywords":[],"products":products,"evidence":[],"source_summary":{}}


def product(niche="test niche", **kwargs):
    result={"niche":niche,"marketplace":"amazon.ae","asin":None,"title":"Test product","brand":None,"current_price_aed":None,"rating":None,"review_count":None,"sponsored_status":None,"search_position":None,"weight_kg":None,"variation_count":None}
    result.update(kwargs); return result


def qualified_records(niche="test niche"):
    return [
        ev("p1","observed_market_price_aed",80,niche=niche),
        ev("d1","amazon_search_volume",500,niche=niche,provider="structured_provider",source_type="structured_amazon_demand",confidence="HIGH"),
        ev("c1","visible_competing_products",6,niche=niche), ev("c2","brand","A",niche=niche), ev("c3","brand","B",niche=niche),
        ev("r1","regulatory_risk","LOW",niche=niche,relevance="UAE_GENERAL",provider="uae_government",source_type="official_government_web",confidence="HIGH",url="https://u.ae/regulation"),
        ev("f1","estimated_referral_fee_aed",12,niche=niche,provider="amazon_public",source_type="official_fee_schedule",confidence="HIGH",url="https://sell.amazon.ae/pricing"),
        ev("fb1","fee_calculation_price_aed",80,niche=niche,provider="amazon_public",source_type="official_fee_schedule",confidence="HIGH",url="https://sell.amazon.ae/pricing")]


class V11CorrectnessTests(unittest.TestCase):
    def test_zero_demand_has_null_score_and_failed_gate(self):
        result=analyze_evidence_bundle(raw([product()]), [ev("p","observed_market_price_aed",80),ev("r","regulatory_risk","LOW",relevance="UAE_GENERAL")], generated_at=NOW)[0]
        self.assertIsNone(result["demand_score"]); self.assertFalse(result["gates"]["demand"]["gate"]); self.assertEqual(result["demand_status"],"UNKNOWN")

    def test_review_count_alone_is_not_demand(self):
        result=analyze_evidence_bundle(raw([product()]), [ev("reviews","review_count",100)], generated_at=NOW)[0]
        self.assertIsNone(result["demand_score"]); self.assertFalse(result["gates"]["demand"]["gate"])

    def test_unknown_competition_does_not_create_attractiveness(self):
        result=analyze_evidence_bundle(raw([product()]), [], generated_at=NOW)[0]
        self.assertIsNone(result["competition_score"]); self.assertEqual(result["competition_status"],"UNKNOWN"); self.assertFalse(result["gates"]["competition"]["gate"])

    def test_one_competitor_dimension_is_insufficient(self):
        result=analyze_evidence_bundle(raw([product()]), [ev("c","visible_competing_products",1)], generated_at=NOW)[0]
        self.assertIsNone(result["competition_score"]); self.assertIn(result["competition_status"],{"PARTIAL","INSUFFICIENT"})

    def test_below_floor_price_rejected(self):
        result=analyze_evidence_bundle(raw([product()]), [ev("p","observed_market_price_aed",25)], generated_at=NOW)[0]
        self.assertFalse(result["gates"]["price"]["gate"]); self.assertEqual(result["recommendation_tier"],"REJECTED_CONSTRAINT")

    def test_external_uae_price_cannot_pass_amazon_gate(self):
        records=[ev("p","observed_market_price_aed",130,relevance="UAE_RETAIL",provider="namshi_uae",source_type="uae_retailer",url="https://namshi.com/product")]
        result=analyze_evidence_bundle(raw([product()]),records,generated_at=NOW)[0]
        self.assertFalse(result["gates"]["price"]["gate"]); self.assertIsNone(result["observed_market_price_aed"]); self.assertEqual(result["external_uae_retail_prices_aed"],[130.0])

    def test_bundle_keeps_prices_separate_and_fee_basis_explicit(self):
        p=product(title="Two pack target bundle",candidate_type="BUNDLE_HYPOTHESIS",proposed_selling_price_aed=69,fee_calculation_price_aed=69)
        result=analyze_evidence_bundle(raw([p]),[ev("p","observed_market_price_aed",25.69),ev("fee","estimated_referral_fee_aed",6.9,provider="amazon_public",source_type="official_fee_schedule",url="https://sell.amazon.ae/pricing")],generated_at=NOW)[0]
        self.assertEqual(result["candidate_type"],"BUNDLE_HYPOTHESIS"); self.assertEqual(result["observed_market_price_aed"],25.69); self.assertEqual(result["proposed_selling_price_aed"],69); self.assertEqual(result["fee_calculation_price_aed"],69); self.assertFalse(result["gates"]["price"]["gate"]); self.assertFalse(result["top_3_to_source_eligible"])
        self.assertEqual(result["fee_scenarios"]["maximum_landed_cost_before_unknown_fba_fee"],44.85)

    def test_missing_critical_component_only_preliminary(self):
        records=qualified_records(); records=[r for r in records if r.metric_name not in {"amazon_search_volume"}]
        result=analyze_evidence_bundle(raw([product(),product(title="Second")]),records,generated_at=NOW)[0]
        self.assertIsNotNone(result["preliminary_opportunity_score"]); self.assertIsNone(result["validated_opportunity_score"])

    def test_confidence_below_60_prevents_sourcing(self):
        result=analyze_evidence_bundle(raw([product()]),[ev("p","observed_market_price_aed",80,confidence="LOW")],generated_at=NOW)[0]
        self.assertLess(result["data_confidence_score"],60); self.assertFalse(result["top_3_to_source_eligible"])

    def test_official_source_status_is_derived_as_used(self):
        records=[ev("fee","estimated_referral_fee_aed",10,provider="amazon_public",source_type="official_fee_schedule",url="https://sell.amazon.ae/pricing")]
        self.assertEqual(source_status_from_evidence(records)["Amazon UAE official pages"],"USED")
        report=render_research_report(raw([product()]),analyze_evidence_bundle(raw([product()]),records,generated_at=NOW),{"Amazon UAE official pages":"UNAVAILABLE"},generated_at=NOW)
        self.assertIn("Amazon UAE official pages: USED",report); self.assertNotIn("Amazon UAE official pages: UNAVAILABLE",report)

    def test_future_and_naive_timestamps_rejected(self):
        base={"id":"x","metric_name":"brand","metric_value":"A","metric_unit":None,"asin":None,"keyword":None,"niche":"n","marketplace":"amazon.ae","source_provider":"codex_web","source_type":"web_search","source_url":None,"source_title":None,"confidence":"LOW","is_estimate":False,"notes":None}
        with self.assertRaisesRegex(ValueError,"timezone"): EvidenceRecord.from_dict({**base,"observed_at":"2026-08-12T10:00:00","retrieved_at":"2026-08-12T10:00:00"},"r",validation_time=NOW)
        future=(NOW+timedelta(minutes=6)).isoformat()
        with self.assertRaisesRegex(ValueError,"future"): EvidenceRecord.from_dict({**base,"observed_at":future,"retrieved_at":future},"r",validation_time=NOW)

    def test_future_run_timestamps_are_rejected_or_explicitly_recorded(self):
        bundle=raw([product()]); bundle["evidence"]=[{"id":"x","metric_name":"brand","metric_value":"A","metric_unit":None,"asin":None,"keyword":None,"niche":"test niche","marketplace":"amazon.ae","source_provider":"codex_web","source_type":"web_search","source_url":None,"source_title":None,"observed_at":(NOW-timedelta(minutes=1)).isoformat(),"retrieved_at":(NOW-timedelta(minutes=1)).isoformat(),"confidence":"LOW","is_estimate":False,"notes":None}]
        bundle["research_run"]["started_at"]=(NOW+timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(ValueError,"started_at is in the future"): validate_bundle(copy.deepcopy(bundle),validation_time=NOW)
        checked,_=validate_bundle(bundle,validation_time=NOW,quarantine_future=True)
        self.assertEqual(checked["_validation_errors"][0]["field"],"started_at")

    def test_utc_and_uae_offset_normalize_identically(self):
        one=ev("a","brand","A",observed=NOW-timedelta(hours=4))
        raw_e={"id":"b","metric_name":"brand","metric_value":"A","metric_unit":None,"asin":None,"keyword":None,"niche":"test niche","marketplace":"amazon.ae","market_relevance":"AMAZON_UAE","source_provider":"codex_web","source_type":"web_search","source_url":None,"source_title":None,"observed_at":"2026-08-12T12:00:00+04:00","retrieved_at":"2026-08-12T12:00:00+04:00","confidence":"LOW","is_estimate":False,"notes":None}
        two=EvidenceRecord.from_dict(raw_e,"r",validation_time=NOW)
        self.assertEqual(one.observed_at,two.observed_at)

    def test_cutoff_never_after_generated(self):
        record=ev("a","brand","A",observed=NOW-timedelta(minutes=1))
        self.assertLessEqual(datetime.fromisoformat(evidence_cutoff([record],NOW).replace("Z","+00:00")),NOW)

    def test_stale_price_and_demand_cannot_pass(self):
        stale=NOW-timedelta(days=40)
        records=[ev("p","observed_market_price_aed",80,observed=stale),ev("d","bestseller_rank",10,observed=stale,confidence="HIGH")]
        result=analyze_evidence_bundle(raw([product()]),records,generated_at=NOW)[0]
        self.assertFalse(result["gates"]["price"]["gate"]); self.assertFalse(result["gates"]["demand"]["gate"])

    def test_funnel_is_canonical_and_invariants_hold(self):
        analyses=analyze_evidence_bundle(raw([product()],funnel={"ideas_generated":60,"screened":30,"meaningful_evidence":15,"finalists":10}),[],generated_at=NOW)
        funnel=canonical_funnel({"ideas_generated":60,"screened":30,"meaningful_evidence":15,"finalists":10},analyses); validate_funnel_invariants(funnel)
        self.assertEqual(funnel["generated"],60); self.assertEqual(funnel["screened"],30); self.assertEqual(funnel["finalists"],0)

    def test_invalid_funnel_invariant_rejected(self):
        with self.assertRaises(ValueError): validate_funnel_invariants({"generated":1,"screened":2,"evidence_backed":0,"validated":0,"finalists":0})

    def test_fewer_than_ten_does_not_promote_gaps(self):
        r=raw([product()]); analyses=analyze_evidence_bundle(r,[],generated_at=NOW); report=render_research_report(r,analyses,generated_at=NOW)
        self.assertIn("QUALIFIED FINALISTS — 0",report); self.assertNotIn("## TOP 10",report); self.assertIn("weak candidates were not promoted",report)

    def test_bundle_never_top_three_to_source(self):
        p=product(candidate_type="BUNDLE_HYPOTHESIS",proposed_selling_price_aed=80,fee_calculation_price_aed=80)
        result=analyze_evidence_bundle(raw([p,product(title="Second")]),qualified_records(),generated_at=NOW)[0]
        self.assertEqual(result["recommendation_tier"],"BUNDLE_HYPOTHESIS"); self.assertFalse(result["top_3_to_source_eligible"])

    def test_fixture_defines_real_regression_classes(self):
        cases=json.load(open("tests/fixtures/v11_regression_cases.json"))
        self.assertEqual(set(cases),{"case_a","case_b","case_c"})
