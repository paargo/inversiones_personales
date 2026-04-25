import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from analysis_models import AnalyzedTicker
from alert_rules import (
    CompositeRule,
    EMACrossRule,
    InsufficientHistoricalDataError,
    PriceCrossEMARule,
    PriceThresholdRule,
    build_alert_rule,
)
from alert_service import RuleBasedAlertService
from market_history_service import HistoricalMarketDataService, MockMarketDataProvider, SqliteMarketHistoryRepository


class SequenceProvider(MockMarketDataProvider):
    def __init__(self, closes):
        self.closes = closes

    def get_historical_ohlc(self, symbol, market, timeframe="1D", start_date=None, end_date=None):
        bars = []
        current = start_date or date(2026, 1, 1)
        for idx, close in enumerate(self.closes):
            bar = type("Bar", (), {})()
            bar.timestamp = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)
            bar.open = close
            bar.high = close
            bar.low = close
            bar.close = close
            bar.volume = 1000 + idx
            bars.append(bar)
            current += timedelta(days=1)
        return bars


class TestRuleBasedAlertService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.repo = SqliteMarketHistoryRepository(self.tmp.name)
        self.ticker = AnalyzedTicker(
            symbol="AAPL",
            market="NYSE",
            asset_type="stock",
            timeframe="1D",
            is_active=True,
        )

    def tearDown(self):
        try:
            import os

            os.unlink(self.tmp.name)
        except Exception:
            pass

    def _service(self, closes):
        return RuleBasedAlertService(
            history_service=HistoricalMarketDataService(SequenceProvider(closes), self.repo),
            repository=self.repo,
        )

    def test_price_threshold_gt_triggers_bullish_alert(self):
        service = self._service([10] * 41 + [25])
        rule = PriceThresholdRule(
            rule_id="price_over_20",
            threshold=20,
            comparator="gt",
            signal="bullish",
        )

        alert = service.evaluate_one(
            self.ticker,
            rule,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "price_threshold")
        self.assertEqual(alert["signal"], "bullish")

    def test_price_threshold_lt_triggers_bearish_alert(self):
        service = self._service([30] * 41 + [12])
        rule = PriceThresholdRule(
            rule_id="price_below_20",
            threshold=20,
            comparator="lt",
            signal="bearish",
        )

        alert = service.evaluate_one(
            self.ticker,
            rule,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "price_threshold")
        self.assertEqual(alert["signal"], "bearish")

    def test_price_cross_ema_triggers_on_last_bar(self):
        service = self._service([10] * 40 + [0, 100])
        rule = PriceCrossEMARule(
            rule_id="price_cross_ema20",
            ema_period=20,
            signal="bullish",
        )

        alert = service.evaluate_one(
            self.ticker,
            rule,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "price_cross_ema")
        self.assertEqual(alert["signal"], "bullish")

    def test_composite_all_triggers_single_alert(self):
        service = self._service([10] * 40 + [0, 100])
        rule = CompositeRule(
            rule_id="bullish_combo",
            signal="bullish",
            operator="all",
            rules=[
                PriceThresholdRule(
                    rule_id="price_over_90",
                    threshold=90,
                    comparator="gt",
                    signal="bullish",
                ),
                PriceCrossEMARule(
                    rule_id="price_cross_ema20",
                    ema_period=20,
                ),
            ],
        )

        alert = service.evaluate_one(
            self.ticker,
            rule,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertIsNotNone(alert)
        self.assertEqual(alert["type"], "group")
        self.assertEqual(alert["signal"], "bullish")
        self.assertEqual(alert["rule_id"], "bullish_combo")

    def test_build_rule_from_dict(self):
        service = self._service([10] * 40 + [0, 100])
        spec = {
            "id": "combo_from_spec",
            "kind": "group",
            "operator": "all",
            "signal": "bullish",
            "rules": [
                {
                    "id": "price_over_90",
                    "kind": "price_threshold",
                    "threshold": 90,
                    "comparator": "gt",
                    "signal": "bullish",
                },
                {
                    "id": "price_cross_ema20",
                    "kind": "price_cross_ema",
                    "ema_period": 20,
                    "signal": "bullish",
                },
            ],
        }

        alert = service.evaluate_from_specs(
            self.ticker,
            [spec],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )[0]

        self.assertEqual(alert["type"], "group")
        self.assertEqual(alert["rule_id"], "combo_from_spec")

    def test_price_cross_ema_requires_enough_bars(self):
        service = self._service([10] * 5)
        rule = PriceCrossEMARule(rule_id="price_cross_ema20", ema_period=20)

        with self.assertRaises(InsufficientHistoricalDataError):
            service.evaluate_one(self.ticker, rule, persist_missing=False)


if __name__ == "__main__":
    unittest.main()
