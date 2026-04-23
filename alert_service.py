"""Basic alert service for EMA10/EMA20 crossovers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from analysis_models import AnalyzedTicker
from market_history_service import (
    HistoricalMarketDataService,
    MockMarketDataProvider,
    OHLCBar,
    SqliteMarketHistoryRepository,
    YFinanceMarketDataProvider,
)
from utils import calculateEMA


class AlertServiceError(Exception):
    """Base exception for EMA alert evaluation."""


class NoHistoricalDataError(AlertServiceError):
    """Raised when no OHLC data is available."""


class InsufficientHistoricalDataError(AlertServiceError):
    """Raised when there are not enough bars to calculate EMA10/EMA20.""" 


class EmaCrossAlertService:
    """Evaluate EMA cross alerts for a ticker."""

    def __init__(
        self,
        history_service: Optional[HistoricalMarketDataService] = None,
        repository: Optional[SqliteMarketHistoryRepository] = None,
    ) -> None:
        self.repository = repository or SqliteMarketHistoryRepository("market_history.sqlite")
        self.history_service = history_service or HistoricalMarketDataService(
            provider=YFinanceMarketDataProvider(),
            repository=self.repository,
        )

    def evaluate(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        persist_missing: bool = True,
    ) -> Optional[dict]:
        ticker = self._normalize_ticker(ticker)
        bars = self._load_bars(ticker, start_date=start_date, end_date=end_date, persist_missing=persist_missing)
        if not bars:
            raise NoHistoricalDataError(
                f"No historical data available for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        closes = [bar.close for bar in bars]
        if len(closes) < 20:
            raise InsufficientHistoricalDataError(
                f"Need at least 20 closing prices to evaluate EMA10/EMA20 for {ticker.symbol}; got {len(closes)}"
            )

        ema10 = calculateEMA(closes, 10)
        ema20 = calculateEMA(closes, 20)
        aligned = self._align_valid_series(ema10, ema20)
        if not aligned:
            raise InsufficientHistoricalDataError(
                f"Not enough overlapping EMA data for {ticker.symbol} to evaluate crossovers"
            )

        ema10_aligned, ema20_aligned, offset = aligned
        if len(ema10_aligned) < 2:
            raise InsufficientHistoricalDataError(
                f"Need at least two aligned EMA values for {ticker.symbol} to evaluate the last crossover"
            )

        prev_diff = ema10_aligned[-2] - ema20_aligned[-2]
        curr_diff = ema10_aligned[-1] - ema20_aligned[-1]

        signal = None
        if prev_diff <= 0 and curr_diff > 0:
            signal = "bullish"
        elif prev_diff >= 0 and curr_diff < 0:
            signal = "bearish"

        if signal is None:
            return None
        return {
            "ticker": ticker.symbol,
            "type": "ema_cross",
            "signal": signal,
            "timestamp": bars[offset + len(ema10_aligned) - 1].timestamp.isoformat(),
        }

    def _normalize_ticker(self, ticker: AnalyzedTicker) -> AnalyzedTicker:
        if ticker.timeframe != "1D":
            raise AlertServiceError("Only daily timeframe (1D) is supported for EMA alerts")
        return ticker

    def _load_bars(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date],
        end_date: Optional[date],
        persist_missing: bool,
    ):
        bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
        if bars:
            return bars

        effective_end = end_date or datetime.now(timezone.utc).date()
        effective_start = start_date or (effective_end - timedelta(days=90))
        bars = self.history_service.investigate(
            ticker,
            start_date=effective_start,
            end_date=effective_end,
        )
        if bars and persist_missing:
            self.history_service.save_ticker_bars(ticker, bars)
        return bars

    @staticmethod
    def _align_valid_series(series_a, series_b):
        start_index = None
        for idx, (a, b) in enumerate(zip(series_a, series_b)):
            if a is not None and b is not None:
                start_index = idx
                break

        if start_index is None:
            return None

        return series_a[start_index:], series_b[start_index:], start_index


EXAMPLE_TICKER = AnalyzedTicker(
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)


def example_usage() -> Optional[dict]:
    """Example using the mock provider for local execution."""
    repo = SqliteMarketHistoryRepository("ema_alert_example.sqlite")
    service = EmaCrossAlertService(
        history_service=HistoricalMarketDataService(
            provider=MockMarketDataProvider(),
            repository=repo,
        ),
        repository=repo,
    )
    return service.evaluate(EXAMPLE_TICKER, persist_missing=True)
