import unittest
from amazon_scout.profitability import analyze_economics, landed_cost, maximum_landed_cost


class ProfitabilityTests(unittest.TestCase):
    def test_landed_cost_and_profitability(self):
        self.assertEqual(landed_cost(20, 5, 2, 1, 2), 30)
        result = analyze_economics(100, 20, 30)
        self.assertEqual(result.profit_before_tax, 50)
        self.assertAlmostEqual(result.roi_on_landed_cost, 5 / 3)
        self.assertEqual(result.net_margin, .5)

    def test_max_landed_cost_targets(self):
        self.assertEqual(maximum_landed_cost(100, 20, .25), 55)
        self.assertIsNone(maximum_landed_cost(0, 20, .25))
        self.assertIsNone(maximum_landed_cost(100, None, .25))

    def test_missing_cost_or_fees_and_negative_margin(self):
        self.assertIsNone(analyze_economics(100, None, 30).profit_before_tax)
        self.assertIsNone(analyze_economics(50, 20, None).net_margin)
        self.assertEqual(analyze_economics(50, 20, 40).net_margin, -.2)
