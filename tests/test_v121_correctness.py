from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from amazon_scout.evidence import EvidenceRecord
from amazon_scout.research_pipeline import analyze_evidence_bundle
from amazon_scout.risk_gap import build_risk_gap_plan, risk_only_gaps
from amazon_scout.sources.serpapi import SerpApiBudget, classify_relevance, normalize_search_response

NOW=datetime(2026,8,12,1,0,tzinfo=timezone.utc); TS=NOW.isoformat()


def result(asin,title,price): return {"position":1,"asin":asin,"title":title,"price":f"AED {price}","extracted_price":price,"rating":4.2,"reviews":20}
def response(items): return {"search_metadata":{"status":"Success"},"search_parameters":{"engine":"amazon","amazon_domain":"amazon.ae","k":"compression packing cubes"},"organic_results":items}


class V121CorrectnessTests(unittest.TestCase):
    def test_accessory_exclusion(self):
        c=classify_relevance(result("B0TEST0001","Replacement strap for compression packing cube",5),"compression packing cubes","compression packing cubes")
        self.assertEqual(c["relevance_status"],"ACCESSORY")

    def test_wrong_product_exclusion(self):
        c=classify_relevance(result("B0TEST0002","Luxury travel neck pillow",300),"compression packing cubes","compression packing cubes")
        self.assertEqual(c["relevance_status"],"WRONG_PRODUCT")

    def test_close_variant_inclusion(self):
        c=classify_relevance(result("B0TEST0003","Travel packing cube organizer",90),"compression packing cubes","compression packing cubes")
        self.assertEqual(c["relevance_status"],"CLOSE_VARIANT")

    def test_ambiguous_exclusion(self):
        c=classify_relevance(result("B0TEST0004","Travel organizer",70),"compression packing cubes","compression packing cubes")
        self.assertEqual(c["relevance_status"],"AMBIGUOUS")

    def test_cheap_accessory_and_unrelated_high_price_do_not_affect_median(self):
        items=[result("B0TEST0001","Compression packing cubes travel set",80),result("B0TEST0002","Travel packing cube organizer",100),result("B0TEST0003","Replacement strap for compression packing cube",5),result("B0TEST0004","Luxury travel neck pillow",900)]
        out=normalize_search_response(response(items),niche="compression packing cubes",keyword="compression packing cubes",run_id="r",retrieved_at=TS)
        self.assertEqual(out["aggregates"]["price_median_aed"],90); self.assertEqual(out["aggregates"]["combined_validated_price_sample"],[80.0,100.0])
        self.assertEqual(out["aggregates"]["excluded_accessories"],1); self.assertEqual(out["aggregates"]["excluded_wrong_products"],1)

    def test_cheap_accessory_alone_does_not_affect_median(self):
        items=[result("B0TEST0001","Compression packing cubes travel set",80),result("B0TEST0002","Compression packing cubes luggage set",100),result("B0TEST0003","Replacement strap for compression packing cube",1)]
        out=normalize_search_response(response(items),niche="compression packing cubes",keyword="compression packing cubes",run_id="r2",retrieved_at=TS)
        self.assertEqual(out["aggregates"]["price_median_aed"],90)

    def test_unrelated_high_price_alone_does_not_affect_median(self):
        items=[result("B0TEST0001","Compression packing cubes travel set",80),result("B0TEST0002","Compression packing cubes luggage set",100),result("B0TEST0004","Luxury travel neck pillow",5000)]
        out=normalize_search_response(response(items),niche="compression packing cubes",keyword="compression packing cubes",run_id="r3",retrieved_at=TS)
        self.assertEqual(out["aggregates"]["price_median_aed"],90)

    def test_pet_mat_cheap_target_is_not_removed_because_of_price(self):
        c=classify_relevance(result("B0TEST0005","Silicone Pet Feeding Mats Nonslip Waterproof with Raised Edges",6.02),"XL silicone pet feeding mats","silicone pet feeding mat")
        self.assertIn(c["relevance_status"],{"EXACT_TARGET","CLOSE_VARIANT"})

    def test_risk_gap_plan_is_zero_paid_and_does_not_touch_budget(self):
        analysis={"niche":"packing cubes","gates":{"price":{"gate":True},"demand":{"gate":True},"competition":{"gate":True},"risk":{"gate":False},"confidence":{"gate":False}}}
        budget=SerpApiBudget(True,40,1); before=budget.calls_attempted; plan=build_risk_gap_plan([analysis],budget.usage(configured=True))
        self.assertTrue(plan["triggered"]); self.assertEqual(plan["additional_serpapi_calls"],0); self.assertEqual(budget.calls_attempted,before)

    def test_risk_gap_trigger_requires_other_three_gates(self):
        passing={"niche":"desk mat","gates":{"price":{"gate":True},"demand":{"gate":True},"competition":{"gate":True},"risk":{"gate":False},"confidence":{"gate":False}}}
        failing={"niche":"unknown price","gates":{"price":{"gate":False},"demand":{"gate":True},"competition":{"gate":True},"risk":{"gate":False},"confidence":{"gate":False}}}
        self.assertEqual([x["niche"] for x in risk_only_gaps([passing,failing])],["desk mat"])

    def test_unknown_risk_remains_unknown_without_evidence(self):
        fixture=json.load(open("tests/fixtures/serpapi_amazon_ae_search.json")); normalized=normalize_search_response(fixture,niche="pet mats",keyword="silicone pet feeding mat",run_id="r",retrieved_at=TS)
        records=[EvidenceRecord.from_dict(x,"r",validation_time=NOW) for x in normalized["evidence"]]
        raw={"research_run":{"id":"r","marketplace":"amazon.ae","started_at":TS,"evidence_cutoff":TS,"filters":{"price_min_aed":50,"price_max_aed":150},"candidate_funnel":{"generated":1,"screened":1}},"keywords":[],"products":normalized["products"],"evidence":normalized["evidence"],"source_summary":{}}
        a=analyze_evidence_bundle(raw,records,generated_at=NOW)[0]; self.assertEqual(a["risk_status"],"UNKNOWN"); self.assertIsNone(a["risk_score"])

    def test_candidate_rescored_after_authoritative_risk_evidence(self):
        fixture=json.load(open("tests/fixtures/serpapi_amazon_ae_search.json")); fixture["organic_results"].append({"position":6,"asin":"B0AE000006","sponsored":False,"brand":"PawTray","title":"Silicone Pet Feeding Mat Large Waterproof Raised Edge","rating":4.3,"reviews":64,"price":"AED 79","extracted_price":79.0,"link_clean":"https://www.amazon.ae/dp/B0AE000006"}); normalized=normalize_search_response(fixture,niche="pet mats",keyword="silicone pet feeding mat",run_id="r",retrieved_at=TS)
        records=[EvidenceRecord.from_dict(x,"r",validation_time=NOW) for x in normalized["evidence"]]
        raw={"research_run":{"id":"r","marketplace":"amazon.ae","started_at":TS,"evidence_cutoff":TS,"filters":{"price_min_aed":50,"price_max_aed":150},"candidate_funnel":{"generated":1,"screened":1}},"keywords":[],"products":normalized["products"],"evidence":normalized["evidence"],"source_summary":{}}
        before=analyze_evidence_bundle(raw,records,generated_at=NOW)[0]
        risk=EvidenceRecord.from_dict({"id":"risk","metric_name":"risk_score","metric_value":25,"metric_unit":"score_0_100","asin":None,"keyword":None,"niche":"pet mats","marketplace":"amazon.ae","market_relevance":"UAE_GENERAL","source_provider":"uae_government","source_type":"official_government_web","source_url":"https://u.ae/en/information-and-services/business/regulations","source_title":"UAE regulations","observed_at":TS,"retrieved_at":TS,"confidence":"HIGH","is_estimate":True,"notes":"Low-complexity non-electrical product; material claims still require supplier verification."},"r",validation_time=NOW)
        after=analyze_evidence_bundle(raw,records+[risk],generated_at=NOW)[0]
        self.assertFalse(before["gates"]["risk"]["gate"]); self.assertTrue(after["gates"]["risk"]["gate"]); self.assertGreater(after["data_confidence_score"],before["data_confidence_score"]); self.assertIsNotNone(after["validated_opportunity_score"])


if __name__=="__main__": unittest.main()
