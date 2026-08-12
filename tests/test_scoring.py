from datetime import datetime, timezone
import unittest
from amazon_scout.scoring import data_confidence, load_scoring_config, opportunity_score, score_label


class ScoringTests(unittest.TestCase):
    def test_deterministic_score(self):
        cfg = load_scoring_config()
        factors = {key: 80 for key in cfg["weights"]}
        self.assertEqual(opportunity_score(factors, cfg["weights"]), 80)
        self.assertEqual(score_label(80, cfg["bands"]), "Strong candidate")

    def test_missing_metric_is_conservative(self):
        cfg = load_scoring_config()
        factors = {key: 100 for key in cfg["weights"]}
        factors["demand"] = None
        self.assertEqual(opportunity_score(factors, cfg["weights"]), 70)

    def test_bad_weights_and_confidence_without_brand_analytics(self):
        with self.assertRaises(ValueError): opportunity_score({"a": 50}, {"a": .5})
        cfg = load_scoring_config()
        score = data_confidence(brand_analytics=False, pricing=True, sales_rank=False, sample_size=1, fee_estimate=False, newest_observation=datetime.now(timezone.utc).isoformat(), config=cfg)
        self.assertEqual(score, 33)
