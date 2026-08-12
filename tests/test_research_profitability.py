import unittest
from amazon_scout.profitability import uncertain_fee_scenarios


class ResearchProfitabilityTests(unittest.TestCase):
    def test_fee_uncertainty_and_landed_cost_scenarios(self):
        result = uncertain_fee_scenarios(100, 15, (5, 10, 20), landed=40)
        self.assertEqual(result["maximum_landed_cost_before_unknown_fba_fee"], 60)
        self.assertEqual(result["maximum_landed_cost_mid_fee_scenario"], 50)
        self.assertEqual(result["estimated_profit_high_fee_scenario"], 25)
        self.assertGreater(result["maximum_landed_cost_low_fee_scenario"], result["maximum_landed_cost_high_fee_scenario"])
