import unittest

from utils import detectCrossovers


class TestDetectCrossovers(unittest.TestCase):
    def test_detects_bullish_crossover(self):
        series_a = [10, 9, 8, 9, 11, 12]
        series_b = [10, 9, 9, 9, 10, 11]

        events = detectCrossovers(series_a, series_b)

        self.assertEqual(events, [{"index": 4, "type": "bullish"}])

    def test_detects_bearish_crossover(self):
        series_a = [12, 11, 10, 9, 8]
        series_b = [10, 10, 10, 10, 10]

        events = detectCrossovers(series_a, series_b)

        self.assertEqual(events, [{"index": 3, "type": "bearish"}])

    def test_ignores_touching_without_crossing(self):
        series_a = [10, 10, 10, 11]
        series_b = [10, 10, 10, 10]

        events = detectCrossovers(series_a, series_b)

        self.assertEqual(events, [])

    def test_handles_multiple_crossovers(self):
        series_a = [9, 11, 9, 11, 9]
        series_b = [10, 10, 10, 10, 10]

        events = detectCrossovers(series_a, series_b)

        self.assertEqual(
            events,
            [
                {"index": 1, "type": "bullish"},
                {"index": 2, "type": "bearish"},
                {"index": 3, "type": "bullish"},
                {"index": 4, "type": "bearish"},
            ],
        )

    def test_rejects_length_mismatch(self):
        with self.assertRaises(ValueError):
            detectCrossovers([1, 2, 3], [1, 2])


if __name__ == "__main__":
    unittest.main()
