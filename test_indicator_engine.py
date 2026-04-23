import tempfile
import unittest

from analysis_models import AnalyzedTicker, IndicatorConfig
from indicator_engine import (
    IndicatorEngine,
    IndicatorRepository,
    MissingIndicatorConfigError,
    NoHistoricalDataError,
)
from market_history_service import HistoricalMarketDataService, MockMarketDataProvider


class TestIndicatorEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self.tmp.close()
        self.repo = IndicatorRepository(self.tmp.name)
        self.history = HistoricalMarketDataService(MockMarketDataProvider(), self.repo)
        self.engine = IndicatorEngine(repository=self.repo, history_service=self.history)
        self.ticker = AnalyzedTicker(
            symbol="AAPL",
            market="NYSE",
            asset_type="stock",
            timeframe="1D",
            is_active=True,
        )
        self.ticker_id = self.repo.get_or_create_ticker_id(
            symbol=self.ticker.symbol,
            market=self.ticker.market,
            asset_type=self.ticker.asset_type,
            timeframe=self.ticker.timeframe,
            is_active=self.ticker.is_active,
        )

    def tearDown(self):
        try:
            import os
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_generate_emas(self):
        self.repo.save_indicator_config(
            IndicatorConfig(ticker_id=self.ticker_id, ema_periods=[3, 5, 10], enable_rsi=True, enable_macd=False)
        )

        result = self.engine.generate(self.ticker)

        self.assertEqual(result["ticker"], "AAPL")
        self.assertEqual(result["timeframe"], "1D")
        self.assertIn("ema_3", result["indicators"])
        self.assertIn("ema_5", result["indicators"])
        self.assertIn("ema_10", result["indicators"])
        self.assertEqual(len(result["indicators"]["ema_3"]), len(result["indicators"]["ema_5"]))

    def test_missing_config_raises(self):
        with self.assertRaises(MissingIndicatorConfigError):
            self.engine.generate(self.ticker)

    def test_no_history_raises_if_provider_returns_none(self):
        class EmptyProvider(MockMarketDataProvider):
            def get_historical_ohlc(self, *args, **kwargs):
                return []

        engine = IndicatorEngine(
            repository=self.repo,
            history_service=HistoricalMarketDataService(EmptyProvider(), self.repo),
        )
        self.repo.save_indicator_config(
            IndicatorConfig(ticker_id=self.ticker_id, ema_periods=[3], enable_rsi=False, enable_macd=False)
        )
        with self.assertRaises(NoHistoricalDataError):
            engine.generate(self.ticker)


if __name__ == "__main__":
    unittest.main()
