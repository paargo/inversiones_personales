import unittest

import pandas as pd


class TestPandasDateSlice(unittest.TestCase):
    def test_slice_up_to_timestamp_keeps_previous_rows(self):
        series = pd.Series({"2023-01-01": 100.0, "2023-02-01": 101.0})
        series.index = pd.to_datetime(series.index)
        target = pd.to_datetime("2023-01-15")

        result = series.sort_index().loc[:target]

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[-1], 100.0)


if __name__ == "__main__":
    unittest.main()
