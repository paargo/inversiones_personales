import unittest
from unittest.mock import Mock, patch

import market_data as md


class TestUSCpi(unittest.TestCase):
    @patch("market_data.requests.get")
    def test_returns_parsed_observations(self, mock_get):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "observations": [
                {"date": "2024-01-01", "value": "300.1"},
                {"date": "2024-02-01", "value": "."},
                {"date": "2024-03-01", "value": "301.8"},
            ]
        }
        mock_get.return_value = response

        result = md.get_us_cpi("test-key")

        self.assertEqual(
            result,
            {
                "2024-01-01": 300.1,
                "2024-03-01": 301.8,
            },
        )

    @patch("market_data.requests.get")
    def test_returns_empty_dict_when_api_key_missing(self, mock_get):
        result = md.get_us_cpi("")

        self.assertEqual(result, {})
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
