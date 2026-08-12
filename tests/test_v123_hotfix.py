from __future__ import annotations

import unittest
from datetime import datetime, timezone

from amazon_scout.commercial_segments import evaluate_price_gate
from amazon_scout.research_pipeline import canonical_funnel, recommendation_tier
from amazon_scout.research_report import render_research_report
from amazon_scout.serpapi_research import merge_serpapi_usage


def gate(prices: list[float]):
    return evaluate_price_gate(prices, 50, 150, minimum_sample_size=5, minimum_in_target_band_ratio=.4)


class V123HotfixTests(unittest.TestCase):
    def test_laundry_median_24_74_ratio_2_fails(self):
        result=gate([24.74]*49+[50]); self.assertFalse(result.gate); self.assertEqual(result.in_target_band_ratio,.02)

    def test_drying_mat_median_44_05_ratio_30_fails(self):
        result=gate([44.05]*7+[50]*3); self.assertFalse(result.gate); self.assertEqual(result.in_target_band_ratio,.3)

    def test_repotting_median_41_66_ratio_36_fails(self):
        result=gate([41.66]*16+[50]*9); self.assertFalse(result.gate); self.assertEqual(result.in_target_band_ratio,.36)

    def test_picnic_median_48_95_ratio_44_passes_or_rule(self):
        result=gate([48.95]*14+[50]*11); self.assertTrue(result.gate); self.assertEqual(result.in_target_band_ratio,.44)

    def test_pet_mat_median_56_62_ratio_22_passes_by_median(self):
        result=gate([10]*4+[56.62,60]+[200]*3); self.assertTrue(result.gate); self.assertEqual(result.median_price_aed,56.62)

    def test_compression_median_163_59_ratio_30_fails(self):
        result=gate([60]*3+[163.59]*7); self.assertFalse(result.gate); self.assertEqual(result.in_target_band_ratio,.3)

    def test_failed_core_price_gate_cannot_remain_validated_weak(self):
        gates={name:{"gate":name!="price"} for name in ("price","demand","competition","risk","confidence")}
        tier=recommendation_tier("OBSERVED_MARKET_OPPORTUNITY",gates,55,55,80,20,True,65,"PREMIUM_POSITIONING_HYPOTHESIS")
        self.assertEqual(tier,"PREMIUM_POSITIONING_HYPOTHESIS"); self.assertNotEqual(tier,"VALIDATED_WEAK_OPPORTUNITY")

    def test_premium_hypothesis_and_core_validated_cannot_coexist(self):
        gates={name:{"gate":True} for name in ("price","demand","competition","risk","confidence")}; gates["price"]["gate"]=False
        self.assertEqual(recommendation_tier("OBSERVED_MARKET_OPPORTUNITY",gates,70,None,80,20,True,65,"PREMIUM_POSITIONING_HYPOTHESIS"),"PREMIUM_POSITIONING_HYPOTHESIS")

    def test_technical_validation_count_independent_from_score_threshold(self):
        def candidate(technical,strong): return {"technically_validated":technical,"qualified_strong_opportunity":strong,"components":{"demand":{"status":"SUFFICIENT"}},"serpapi_keywords":["x"],"gates":{name:{"gate":True} for name in ("price","demand","competition","risk","confidence")},"candidate_type":"OBSERVED_MARKET_OPPORTUNITY"}
        funnel=canonical_funnel({"generated":3,"screened":3},[candidate(True,False),candidate(True,True),candidate(False,False)])
        self.assertEqual(funnel["technically_validated"],2); self.assertEqual(funnel["strong_opportunities"],1)

    def test_report_uses_canonical_complete_run_usage(self):
        phase1={"configured":True,"enabled":True,"configured_max_calls":40,"calls_attempted":15,"calls_succeeded":15,"calls_failed":0,"calls_saved_by_cache":0,"keywords_queried":["a"],"asins_queried":[],"product_detail_calls":0,"purpose_for_each_call":[]}
        phase2={**phase1,"calls_attempted":5,"calls_succeeded":5,"keywords_queried":["b"]}
        usage=merge_serpapi_usage(phase1,phase2)
        raw={"research_run":{"filters":{},"candidate_funnel":{"generated":0,"screened":0}},"serpapi_usage":usage}
        report=render_research_report(raw,[],generated_at=datetime(2026,8,12,tzinfo=timezone.utc))
        self.assertEqual(usage["calls_attempted"],20); self.assertIn("## SERPAPI USAGE\n\n- Configured: yes",report); self.assertIn("- Calls attempted: 20",report)


if __name__ == "__main__": unittest.main()
