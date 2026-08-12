import unittest

from amazon_scout.economics_v13 import (
    PHYSICAL_ESTIMATES, ProductPhysicalProfile, calculate_candidate_economics,
    fba_fulfillment_fee, fba_size_tier, load_economics_config,
    map_fee_categories, maximum_landed_cost_v13, referral_fee,
    required_economics_raw, score_with_economics, storage_fee,
)
from amazon_scout.scoring import load_scoring_config, opportunity_score_breakdown


class EconomicsV13Tests(unittest.TestCase):
    def setUp(self):
        self.cfg=load_economics_config()

    def test_referral_category_mapping(self): self.assertEqual(map_fee_categories("adjustable airplane foot hammock")["amazon_fee_category"],"LUGGAGE")
    def test_category_ambiguity_has_multiple_scenarios(self): self.assertGreater(len(map_fee_categories("wood crochet blocking board")["category_scenarios"]),1)
    def test_referral_fee_calculation(self): self.assertEqual(referral_fee(100,"HOME")["amount_aed"],15)
    def test_minimum_referral_fee(self): self.assertEqual(referral_fee(2,"HOME")["amount_aed"],1)
    def test_tiered_referral_fee(self): self.assertEqual(referral_fee(50,"PET_PRODUCTS")["rate"],.08)
    def test_fba_size_lookup(self): self.assertEqual(fba_size_tier(PHYSICAL_ESTIMATES["adjustable airplane foot hammock"]),"LARGE_ENVELOPE")
    def test_fba_fee_lookup(self): self.assertEqual(fba_fulfillment_fee(50,PHYSICAL_ESTIMATES["adjustable airplane foot hammock"])["fee_aed"],7.5)
    def test_missing_dimensions(self):
        p=ProductPhysicalProfile(None,None,None,None,None,None,None,None,None,1,"one","UNKNOWN",0)
        self.assertIsNone(fba_size_tier(p)); self.assertEqual(fba_fulfillment_fee(50,p)["status"],"UNKNOWN")
    def test_storage_reserve(self): self.assertGreater(storage_fee(PHYSICAL_ESTIMATES["wood crochet blocking board"],1),0)
    def test_maximum_landed_cost(self): self.assertEqual(maximum_landed_cost_v13(100,.25,25),50)
    def test_margin_targets_monotonic(self):
        e=calculate_candidate_economics("long handle baseboard cleaning tool",123.73)["scenarios"]["BASE"]["maximum_landed_cost_aed"]
        self.assertGreater(e["20"],e["25"]); self.assertGreater(e["25"],e["30"])
    def test_fee_vat(self):
        b=calculate_candidate_economics("long handle baseboard cleaning tool",100)["scenarios"]["BASE"]
        self.assertEqual(b["amazon_fee_vat_aed"],round((b["referral_fee_aed"]+b["fba"]["fee_aed"]+b["storage_fee_estimate_aed"])*.05,2))
    def test_ad_reserve(self): self.assertEqual(calculate_candidate_economics("long handle baseboard cleaning tool",100)["scenarios"]["BASE"]["advertising_reserve_aed"],10)
    def test_return_reserve(self): self.assertEqual(calculate_candidate_economics("long handle baseboard cleaning tool",100)["scenarios"]["BASE"]["returns_refunds_reserve_aed"],5)
    def test_economics_confidence_partial_for_estimate(self):
        e=calculate_candidate_economics("long handle baseboard cleaning tool",100); self.assertEqual(e["status"],"PARTIAL"); self.assertLess(e["confidence"],75)
    def test_unknown_economics_remains_zero(self):
        weights=load_scoring_config()["weights"]; factors={k:100 for k in weights}; factors["margin_potential"]=None
        self.assertEqual(opportunity_score_breakdown(factors,weights)["components"]["margin_potential"]["contribution"],0)
    def test_sufficient_economics_deterministic(self):
        p=ProductPhysicalProfile(None,.8,None,None,None,45,12,10,None,1,"one","SUPPLIER",90)
        a=calculate_candidate_economics("long handle baseboard cleaning tool",100,actual_landed_cost_aed=20,physical_profile=p); b=calculate_candidate_economics("long handle baseboard cleaning tool",100,actual_landed_cost_aed=20,physical_profile=p)
        self.assertEqual(a["score"]["raw"],b["score"]["raw"]); self.assertEqual(a["status"],"SUFFICIENT")
    def test_score_contribution_exactly_twenty_percent(self):
        raw=calculate_candidate_economics("long handle baseboard cleaning tool",100)["score"]["raw"]
        weights=load_scoring_config()["weights"]; factors={key:0 for key in weights}; factors["margin_potential"]=raw
        self.assertEqual(opportunity_score_breakdown(factors,weights)["components"]["margin_potential"]["contribution"],round(raw*.2,4))
    def test_baseboard_threshold_arithmetic(self): self.assertEqual(required_economics_raw(46.55,55),42.25); self.assertEqual(required_economics_raw(46.55,65),92.25)
    def test_fan_threshold_arithmetic(self): self.assertEqual(required_economics_raw(45.68,65),96.6)
    def test_foot_hammock_ceiling(self): self.assertLess(score_with_economics(43.81,100),65)
    def test_crochet_ceiling(self): self.assertLess(score_with_economics(44.72,100),65)
    def test_sensitivity_analysis(self):
        s=calculate_candidate_economics("adjustable airplane foot hammock",49.98)["sensitivity"]
        self.assertEqual(len(s["cases"]),9); self.assertIn(s["classification"],{"ROBUST","SENSITIVE","FRAGILE"})
    def test_import_vat_separate_from_permanent_cost(self):
        s=calculate_candidate_economics("long handle baseboard cleaning tool",100)["scenarios"]["BASE"]
        self.assertIsNone(s["import_vat_cash_flow_aed"]); self.assertIsNotNone(s["supplier_targets"]["25"]["import_vat_cash_flow_aed"])


if __name__ == "__main__": unittest.main()
