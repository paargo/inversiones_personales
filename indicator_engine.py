"""Indicator engine that loads history, reads config, and computes EMAs."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from analysis_models import AnalyzedTicker, IndicatorConfig
from market_history_service import (
    HistoricalMarketDataService,
    MockMarketDataProvider,
    OHLCBar,
    SqliteMarketHistoryRepository,
    YFinanceMarketDataProvider,
)
from utils import calculateEMA


class IndicatorEngineError(Exception):
    """Base error for the indicator engine."""


class TickerNotFoundError(IndicatorEngineError):
    """Raised when the ticker does not exist and cannot be created."""


class MissingIndicatorConfigError(IndicatorEngineError):
    """Raised when there is no indicator config for the ticker."""


class NoHistoricalDataError(IndicatorEngineError):
    """Raised when there are no OHLC bars available for the ticker."""


class IndicatorRepository(SqliteMarketHistoryRepository):
    """SQLite repository that also stores indicator configuration."""

    def _ensure_schema(self) -> None:
        super()._ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS indicator_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker_id INTEGER NOT NULL UNIQUE,
                    ema_periods TEXT NOT NULL,
                    enable_rsi INTEGER NOT NULL DEFAULT 1,
                    enable_macd INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
                )
                """
            )

    def save_indicator_config(self, config: IndicatorConfig) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO indicator_configs (
                    ticker_id, ema_periods, enable_rsi, enable_macd
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker_id) DO UPDATE SET
                    ema_periods = excluded.ema_periods,
                    enable_rsi = excluded.enable_rsi,
                    enable_macd = excluded.enable_macd
                """,
                (
                    config.ticker_id,
                    json.dumps(config.ema_periods),
                    int(config.enable_rsi),
                    int(config.enable_macd),
                ),
            )
            return int(cursor.lastrowid or config.ticker_id)

    def get_indicator_config(self, ticker_id: int) -> Optional[IndicatorConfig]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, ticker_id, ema_periods, enable_rsi, enable_macd
                FROM indicator_configs
                WHERE ticker_id = ?
                """,
                (ticker_id,),
            ).fetchone()

        if not row:
            return None

        ema_periods = json.loads(row["ema_periods"])
        return IndicatorConfig(
            id=int(row["id"]),
            ticker_id=int(row["ticker_id"]),
            ema_periods=ema_periods,
            enable_rsi=bool(row["enable_rsi"]),
            enable_macd=bool(row["enable_macd"]),
        )

    def get_indicator_config_by_identity(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
    ) -> Optional[IndicatorConfig]:
        ticker_id = self.get_ticker_id(symbol, market, timeframe)
        if ticker_id is None:
            return None
        return self.get_indicator_config(ticker_id)


class IndicatorEngine:
    """Coordinates history loading, config loading, and EMA calculation."""

    def __init__(
        self,
        repository: Optional[IndicatorRepository] = None,
        history_service: Optional[HistoricalMarketDataService] = None,
    ) -> None:
        self.repository = repository or IndicatorRepository("market_history.sqlite")
        self.history_service = history_service or HistoricalMarketDataService(
            provider=YFinanceMarketDataProvider(),
            repository=self.repository,
        )

    def generate(self, ticker: AnalyzedTicker) -> Dict:
        ticker = self._normalize_ticker(ticker)
        ticker_id = self._ensure_ticker_id(ticker)
        config = self.repository.get_indicator_config(ticker_id)
        if config is None:
            raise MissingIndicatorConfigError(
                f"No indicator config found for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        bars = self._load_or_fetch_bars(ticker, config.ema_periods)
        if not bars:
            raise NoHistoricalDataError(
                f"No historical OHLC data available for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        closes = [bar.close for bar in bars]
        longest_period = max(config.ema_periods)
        if len(closes) < longest_period:
            raise NoHistoricalDataError(
                f"Not enough historical bars for {ticker.symbol} on {ticker.market} ({ticker.timeframe}): "
                f"need at least {longest_period}, got {len(closes)}"
            )

        indicators = {}
        for period in config.ema_periods:
            indicators[f"ema_{period}"] = calculateEMA(closes, period)

        return {
            "ticker": ticker.symbol,
            "timeframe": ticker.timeframe,
            "indicators": indicators,
        }

    def generate_by_identity(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
        asset_type: str = "stock",
    ) -> Dict:
        ticker = AnalyzedTicker(
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            timeframe=timeframe,
            is_active=True,
        )
        return self.generate(ticker)

    def _normalize_ticker(self, ticker: AnalyzedTicker) -> AnalyzedTicker:
        if ticker.timeframe != "1D":
            raise IndicatorEngineError("Only daily timeframe (1D) is supported for now")
        return ticker

    def _ensure_ticker_id(self, ticker: AnalyzedTicker) -> int:
        if ticker.id:
            return ticker.id
        ticker_id = self.repository.get_ticker_id(ticker.symbol, ticker.market, ticker.timeframe)
        if ticker_id is not None:
            return ticker_id
        return self.repository.get_or_create_ticker_id(
            symbol=ticker.symbol,
            market=ticker.market,
            asset_type=ticker.asset_type,
            timeframe=ticker.timeframe,
            is_active=ticker.is_active,
        )

    def _load_or_fetch_bars(self, ticker: AnalyzedTicker, ema_periods: Sequence[int]) -> List[OHLCBar]:
        bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
        if bars:
            return bars

        longest_period = max(ema_periods) if ema_periods else 10
        lookback_days = max(longest_period * 3, longest_period + 30)
        start_date = datetime.now(timezone.utc).date() - timedelta(days=lookback_days)
        bars = self.history_service.investigate(
            ticker,
            start_date=start_date,
            end_date=datetime.now(timezone.utc).date(),
        )
        if bars:
            self.history_service.save_ticker_bars(ticker, bars)
        return bars


EXAMPLE_TICKER = AnalyzedTicker(
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)


def example_usage() -> Dict:
    """Example using mock market data and a seeded EMA config."""
    temp_repo = IndicatorRepository("indicator_engine_example.sqlite")
    engine = IndicatorEngine(
        repository=temp_repo,
        history_service=HistoricalMarketDataService(
            provider=MockMarketDataProvider(),
            repository=temp_repo,
        ),
    )

    ticker_id = temp_repo.get_or_create_ticker_id(
        symbol=EXAMPLE_TICKER.symbol,
        market=EXAMPLE_TICKER.market,
        asset_type=EXAMPLE_TICKER.asset_type,
        timeframe=EXAMPLE_TICKER.timeframe,
        is_active=EXAMPLE_TICKER.is_active,
    )
    temp_repo.save_indicator_config(
        IndicatorConfig(
            ticker_id=ticker_id,
            ema_periods=[10, 20, 100],
            enable_rsi=False,
            enable_macd=False,
        )
    )
    return engine.generate(EXAMPLE_TICKER)
