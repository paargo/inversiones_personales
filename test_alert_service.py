import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from analysis_models import AnalyzedTicker
from alert_service import (
    EmaCrossAlertService,
    InsufficientHistoricalDataError,
    NoHistoricalDataError,
)
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
            current = current + timedelta(days=1)
        return bars


class TestEmaCrossAlertService(unittest.TestCase):
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

    def test_returns_none_when_no_last_bar_cross(self):
        service = EmaCrossAlertService(
            history_service=HistoricalMarketDataService(SequenceProvider([10] * 42), self.repo),
            repository=self.repo,
        )

        result = service.evaluate(
            self.ticker,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertIsNone(result)

    def test_returns_bullish_alert_when_last_bar_crosses_up(self):
        # The sequence must end with a real bullish crossover on the last bar:
        # EMA10 stays below EMA20 after the drop to 0, then crosses above on the final 100.
        closes = [10] * 40 + [0, 100]
        service = EmaCrossAlertService(
            history_service=HistoricalMarketDataService(SequenceProvider(closes), self.repo),
            repository=self.repo,
        )

        result = service.evaluate(
            self.ticker,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertEqual(
            result,
            {
                "ticker": "AAPL",
                "type": "ema_cross",
                "signal": "bullish",
                "timestamp": "2026-02-11T00:00:00+00:00",
            },
        )

    def test_returns_bearish_alert_when_last_bar_crosses_down(self):
        closes = [50] * 40 + [100, 0]
        service = EmaCrossAlertService(
            history_service=HistoricalMarketDataService(SequenceProvider(closes), self.repo),
            repository=self.repo,
        )

        result = service.evaluate(
            self.ticker,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 2, 11),
            persist_missing=False,
        )

        self.assertEqual(
            result,
            {
                "ticker": "AAPL",
                "type": "ema_cross",
                "signal": "bearish",
                "timestamp": "2026-02-11T00:00:00+00:00",
            },
        )

    def test_raises_when_no_data(self):
        class EmptyProvider(MockMarketDataProvider):
            def get_historical_ohlc(self, *args, **kwargs):
                return []

        service = EmaCrossAlertService(
            history_service=HistoricalMarketDataService(EmptyProvider(), self.repo),
            repository=self.repo,
        )

        with self.assertRaises(NoHistoricalDataError):
            service.evaluate(self.ticker, persist_missing=False)

    def test_raises_when_not_enough_bars(self):
        class ShortProvider(MockMarketDataProvider):
            def get_historical_ohlc(self, symbol, market, timeframe="1D", start_date=None, end_date=None):
                bars = super().get_historical_ohlc(symbol, market, timeframe, start_date, end_date)
                return bars[:10]

        service = EmaCrossAlertService(
            history_service=HistoricalMarketDataService(ShortProvider(), self.repo),
            repository=self.repo,
        )

        with self.assertRaises(InsufficientHistoricalDataError):
            service.evaluate(self.ticker, persist_missing=False)


if __name__ == "__main__":
    unittest.main()
