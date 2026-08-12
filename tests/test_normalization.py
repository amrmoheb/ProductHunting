import unittest
from amazon_scout.normalization import minmax, percentile, price_statistics


class NormalizationTests(unittest.TestCase):
    def test_normalization_and_prices(self):
        self.assertEqual(minmax(5, 0, 10), 50)
        self.assertEqual(minmax(None, 0, 10), 0)
        self.assertEqual(minmax(3, 0, 10, reverse=True), 70)
        self.assertEqual(percentile([1, 2, 3, 4], .25), 1.75)
        self.assertEqual(price_statistics([None, 50, 100])["median"], 75)
        self.assertIsNone(price_statistics([])["median"])
