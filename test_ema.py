import unittest

from utils import calculateEMA


class TestCalculateEMA(unittest.TestCase):
    def test_ema_seeded_with_sma_and_aligned(self):
        prices = [10, 11, 12, 13, 14, 15]
        result = calculateEMA(prices, 3)

        self.assertEqual(result[:2], [None, None])
        self.assertAlmostEqual(result[2], 11.0, places=10)
        self.assertAlmostEqual(result[3], 12.0, places=10)
        self.assertAlmostEqual(result[4], 13.0, places=10)
        self.assertAlmostEqual(result[5], 14.0, places=10)

    def test_ema_with_single_period_matches_prices(self):
        prices = [100.0, 101.5, 102.25]
        result = calculateEMA(prices, 1)

        self.assertEqual(result, prices)

    def test_ema_rejects_invalid_period(self):
        with self.assertRaises(ValueError):
            calculateEMA([1, 2, 3], 0)

    def test_ema_rejects_short_series(self):
        with self.assertRaises(ValueError):
            calculateEMA([1, 2], 3)


if __name__ == "__main__":
    unittest.main()
