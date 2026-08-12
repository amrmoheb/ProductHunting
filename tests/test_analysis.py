import unittest
from amazon_scout.competition import competition_metrics, competition_risk
from amazon_scout.demand import calculate_demand
from amazon_scout.models import Product
from amazon_scout.risks import calculate_risk


class AnalysisTests(unittest.TestCase):
    def test_single_competitor_and_large_catalog(self):
        products = [Product("B000000001", "Simple organizer", brand="OnlyBrand", offer_count=1)]
        metrics = competition_metrics(products, 1_000_000)
        self.assertEqual(metrics["top_brand_share"], 1)
        self.assertTrue(0 <= competition_risk(products, 1_000_000) <= 100)

    def test_missing_sales_rank_and_brand_analytics(self):
        score, confidence = calculate_demand(None, [], 100)
        self.assertGreater(score, 0)
        self.assertEqual(confidence, "LOW")

    def test_risk_terms_and_weight(self):
        product = Product("B000000002", "Glass battery blender", product_type="ELECTRONICS", weight_kg=2)
        score, reasons = calculate_risk("portable blender", [product], 50)
        self.assertGreaterEqual(score, 60)
        self.assertGreaterEqual(len(reasons), 3)
