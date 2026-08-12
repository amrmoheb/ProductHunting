from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from amazon_scout.evidence import EvidenceRecord
from amazon_scout.research_pipeline import analyze_evidence_bundle, canonical_funnel
from amazon_scout.research_report import render_research_report
from amazon_scout.sources.serpapi import SerpApiBudget, SerpApiCache, SerpApiSource, normalize_product_response, normalize_search_response, parse_bought_last_month, request_fingerprint

NOW=datetime(2026,8,12,1,0,tzinfo=timezone.utc); TS=NOW.isoformat()


def fixture(): return json.load(open("tests/fixtures/serpapi_amazon_ae_search.json"))


def relevance(result):
    return (False,"media") if "book" in str(result.get("title","")).lower() else (True,None)


class SerpApiV12Tests(unittest.TestCase):
    def test_request_construction_is_explicit_uae(self):
        self.assertEqual(SerpApiSource.search_params("drawer organizer"),{"engine":"amazon","amazon_domain":"amazon.ae","k":"drawer organizer","page":1})
        self.assertEqual(SerpApiSource.product_params("b0ae000001")["engine"],"amazon_product")

    def test_amazon_com_request_and_response_rejected(self):
        with self.assertRaisesRegex(ValueError,"amazon.ae"): SerpApiSource._validate_params({"engine":"amazon","amazon_domain":"amazon.com","k":"x"})
        bad=fixture(); bad["search_parameters"]["amazon_domain"]="amazon.com"
        with self.assertRaisesRegex(ValueError,"Non-UAE"): SerpApiSource._validate_response(bad,"amazon")

    def test_fingerprint_and_cache_never_include_key(self):
        one=request_fingerprint({"engine":"amazon","amazon_domain":"amazon.ae","k":"x","api_key":"secret-one"})
        two=request_fingerprint({"engine":"amazon","amazon_domain":"amazon.ae","k":"x","api_key":"secret-two"})
        self.assertEqual(one,two); self.assertNotIn("secret",one)

    def test_paid_provider_safety_and_hard_limit(self):
        with self.assertRaises(PermissionError): SerpApiBudget(False,40,1).authorize_request(SerpApiSource.search_params("x"),"test")
        budget=SerpApiBudget(True,2,1,reserve_calls=0)
        budget.authorize_request(SerpApiSource.search_params("a"),"a"); budget.authorize_request(SerpApiSource.search_params("b"),"b")
        with self.assertRaises(PermissionError): budget.authorize_request(SerpApiSource.search_params("c"),"c")

    def test_reserve_protected_unless_high_value(self):
        budget=SerpApiBudget(True,6,1,reserve_calls=5)
        budget.authorize_request(SerpApiSource.search_params("a"),"validation")
        with self.assertRaisesRegex(PermissionError,"reserve"): budget.authorize_request(SerpApiSource.search_params("b"),"generic")
        budget.authorize_request(SerpApiSource.search_params("b"),"gap close",use_reserve=True)

    def test_cache_hit_deduplicates_without_call(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"SERPAPI_API_KEY":"top-secret"},clear=True):
            cache=SerpApiCache(directory,8); params=SerpApiSource.search_params("mat"); cache.put(params,fixture(),NOW)
            budget=SerpApiBudget(True,40,1)
            response,state=SerpApiSource().execute(params,budget,cache,"test")
            self.assertEqual(state,"CACHE"); self.assertEqual(budget.calls_attempted,0); self.assertEqual(budget.calls_saved_by_cache,1); self.assertEqual(budget.keywords_queried,["mat"]); self.assertTrue(response)

    def test_cache_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            cache=SerpApiCache(directory,6); params=SerpApiSource.search_params("mat"); cache.put(params,fixture(),NOW-timedelta(hours=7))
            self.assertIsNone(cache.get(params,NOW))

    def test_normalization_parses_fields_and_exclusions(self):
        out=normalize_search_response(fixture(),niche="pet mats",keyword="silicone pet feeding mat",run_id="r",retrieved_at=TS,relevant=relevance)
        self.assertEqual(out["aggregates"]["total_results_received"],5); self.assertEqual(out["aggregates"]["results_considered_relevant"],4); self.assertEqual(out["aggregates"]["results_excluded"],1)
        first=out["products"][0]; self.assertEqual(first["asin"],"B0AE000001"); self.assertEqual(first["current_price_aed"],89); self.assertEqual(first["rating"],4.5); self.assertEqual(first["reviews"],420); self.assertTrue(first["sponsored"]); self.assertEqual(first["position"],1)

    def test_bought_last_month_is_lower_bound_not_exact(self):
        self.assertEqual(parse_bought_last_month("100+ bought in past month"),("100+ bought in past month",100,False))
        self.assertEqual(parse_bought_last_month("1K+ bought in past month")[1],1000)
        self.assertEqual(parse_bought_last_month(None),(None,None,False))

    def test_competition_aggregates(self):
        a=normalize_search_response(fixture(),niche="pet mats",keyword="mat",run_id="r",retrieved_at=TS,relevant=relevance)["aggregates"]
        self.assertEqual(a["unique_asin_count"],4); self.assertEqual(a["unique_brand_count"],3); self.assertEqual(a["top_brand_share"],.5); self.assertEqual(a["sponsored_density"],.5); self.assertEqual(a["median_reviews"],147.5)
        self.assertEqual(a["in_target_price_band_count"],3); self.assertEqual(a["amazon_uae_price_sample_size"],4)

    def test_non_aed_display_is_not_normalized_as_aed(self):
        data=fixture(); data["organic_results"][0]["price"]="$89"; data["organic_results"][0]["extracted_price"]=89
        out=normalize_search_response(data,niche="pet mats",keyword="mat",run_id="r",retrieved_at=TS,relevant=relevance)
        self.assertIsNone(out["products"][0]["current_price_aed"])

    def test_product_response_normalization(self):
        payload={"search_metadata":{"status":"Success"},"search_parameters":{"engine":"amazon_product","amazon_domain":"amazon.ae","asin":"B0AE000001"},"product_results":{"asin":"B0AE000001","title":"Pet Mat","brand":"PetNeat","price":"AED 89","extracted_price":89,"rating":4.5,"reviews":420,"availability":"In stock"}}
        out=normalize_product_response(payload,niche="pet mats",keyword="B0AE000001",run_id="r",retrieved_at=TS)
        self.assertEqual(out["products"][0]["asin"],"B0AE000001"); self.assertEqual(out["products"][0]["current_price_aed"],89)

    def test_usage_reporting_does_not_claim_account_quota(self):
        budget=SerpApiBudget(True,40,1); usage=budget.usage(configured=True)
        self.assertEqual(usage["calls_remaining"],40); self.assertIn("not SerpApi account quota",usage["local_budget_note"])

    def test_failure_is_unknown_not_zero_and_key_not_leaked(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{"SERPAPI_API_KEY":"super-secret-key"},clear=True):
            budget=SerpApiBudget(True,10,1,reserve_calls=0)
            response,error=SerpApiSource().execute(SerpApiSource.search_params("mat"),budget,SerpApiCache(directory),"test",transport=lambda _: (_ for _ in ()).throw(TimeoutError("secret super-secret-key")))
            self.assertIsNone(response); self.assertNotIn("super-secret-key",error); self.assertEqual(budget.calls_failed,1)

    def test_component_freshness_and_report_classification_are_canonical(self):
        normalized=normalize_search_response(fixture(),niche="pet mats",keyword="mat",run_id="r",retrieved_at=TS,relevant=relevance)
        records=[EvidenceRecord.from_dict(x,"r",validation_time=NOW) for x in normalized["evidence"]]
        raw={"research_run":{"id":"r","slug":"r","marketplace":"amazon.ae","started_at":TS,"evidence_cutoff":TS,"filters":{"price_min_aed":50,"price_max_aed":150},"candidate_funnel":{"generated":60,"screened":12}},"keywords":["mat"],"products":normalized["products"],"evidence":normalized["evidence"],"source_summary":{},"serpapi_usage":{"configured":True,"enabled":True,"configured_max_calls":40,"calls_attempted":1,"calls_succeeded":1,"calls_failed":0,"calls_saved_by_cache":0,"calls_remaining":39,"keywords_queried":["mat"],"product_detail_calls":0}}
        analyses=analyze_evidence_bundle(raw,records,generated_at=NOW); report=render_research_report(raw,analyses,generated_at=NOW)
        self.assertEqual(analyses[0]["component_freshness"]["price"],"CURRENT"); self.assertEqual(analyses[0]["component_freshness"]["risk"],"UNKNOWN")
        tier=analyses[0]["recommendation_tier"]; self.assertEqual(report.count(f"Recommendation tier: **{tier}**"),1)
        self.assertIn("Selling-price basis: CURRENT OBSERVED AMAZON UAE PRICE",report); self.assertIn("Calls attempted: 1",report)
        funnel=canonical_funnel(raw["research_run"]["candidate_funnel"],analyses); self.assertEqual(funnel["generated"],60); self.assertEqual(funnel["serpapi_validated"],1)

    def test_stale_observed_price_with_fee_basis_is_labeled_scenario(self):
        old=(NOW-timedelta(days=20)).isoformat(); normalized=normalize_search_response(fixture(),niche="pet mats",keyword="mat",run_id="old",retrieved_at=old,relevant=relevance)
        normalized["products"][0]["fee_calculation_price_aed"]=90
        records=[EvidenceRecord.from_dict(x,"old",validation_time=NOW) for x in normalized["evidence"]]
        raw={"research_run":{"id":"old","slug":"old","marketplace":"amazon.ae","started_at":old,"evidence_cutoff":old,"filters":{"price_min_aed":50,"price_max_aed":150},"candidate_funnel":{"generated":1,"screened":1}},"keywords":["mat"],"products":normalized["products"],"evidence":normalized["evidence"],"source_summary":{}}
        analyses=analyze_evidence_bundle(raw,records,generated_at=NOW); report=render_research_report(raw,analyses,generated_at=NOW)
        self.assertIn("Observed price freshness: STALE",report); self.assertIn("Selling-price basis: SCENARIO",report)


if __name__=="__main__": unittest.main()
