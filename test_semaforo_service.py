import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from analysis_models import AnalyzedTicker
from semaforo_service import SemaphoreConfig, SemaphoreRepository, SemaphoreService
from market_history_service import HistoricalMarketDataService, MockMarketDataProvider


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


class TestSemaphoreService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.repo = SemaphoreRepository(self.tmp.name)
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
        return SemaphoreService(
            history_service=HistoricalMarketDataService(SequenceProvider(closes), self.repo),
            repository=self.repo,
        )

    def test_calculates_states_and_persists_snapshot(self):
        service = self._service([10] * 120 + [0, 100])
        ticker_id = self.repo.get_or_create_ticker_id(
            symbol="AAPL",
            market="NYSE",
            asset_type="stock",
            timeframe="1D",
            is_active=True,
        )
        self.repo.save_semaphore_config(
            SemaphoreConfig(
                ticker_id=ticker_id,
                enable_price_vs_ema10=True,
                enable_price_vs_ema20=True,
                enable_price_vs_ema100=True,
                enable_ema10_vs_ema20=True,
                enable_price_vs_high=True,
            )
        )

        result = service.calculate(self.ticker, persist_missing=False)

        self.assertEqual(result["ticker"], "AAPL")
        self.assertEqual(result["indicators"]["price_vs_ema10"]["state"], "green")
        self.assertEqual(result["indicators"]["price_vs_ema20"]["state"], "green")
        self.assertEqual(result["indicators"]["ema10_vs_ema20"]["state"], "green")
        self.assertEqual(result["indicators"]["price_vs_high"]["state"], "green")
        self.assertAlmostEqual(result["indicators"]["price_vs_high"]["difference_pct"], 900.0, places=2)
        self.assertIsNotNone(service.get_last_calculated_at(self.ticker))
        snapshot = service.get_latest_snapshot(self.ticker)
        self.assertIsNotNone(snapshot)

    def test_rejects_empty_config(self):
        with self.assertRaises(ValueError):
            SemaphoreConfig(
                ticker_id=1,
                enable_price_vs_ema10=False,
                enable_price_vs_ema20=False,
                enable_price_vs_ema100=False,
                enable_ema10_vs_ema20=False,
                enable_price_vs_high=False,
            )


if __name__ == "__main__":
    unittest.main()
