"""Semaphore-style indicator status service for configured tickers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from analysis_models import AnalyzedTicker
from indicator_engine import IndicatorRepository
from market_history_service import HistoricalMarketDataService, MockMarketDataProvider, OHLCBar
from utils import calculateEMA


class SemaphoreServiceError(Exception):
    """Base error for semaphore calculations."""


class SemaphoreConfigNotFoundError(SemaphoreServiceError):
    """Raised when a ticker has no semaphore configuration."""


class SemaphoreNoHistoricalDataError(SemaphoreServiceError):
    """Raised when there are not enough bars to calculate semaphore values."""


class SemaphoreRepository(IndicatorRepository):
    """Repository with persistence for semaphore configuration and snapshots."""

    def _ensure_schema(self) -> None:
        super()._ensure_schema()
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semaphore_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker_id INTEGER NOT NULL UNIQUE,
                    enable_price_vs_ema10 INTEGER NOT NULL DEFAULT 1,
                    enable_price_vs_ema20 INTEGER NOT NULL DEFAULT 1,
                    enable_price_vs_ema100 INTEGER NOT NULL DEFAULT 1,
                    enable_ema10_vs_ema20 INTEGER NOT NULL DEFAULT 1,
                    enable_price_vs_high INTEGER NOT NULL DEFAULT 1,
                    last_calculated_at TEXT,
                    last_result_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
                )
                """
            )
            self._ensure_column(conn, "semaphore_configs", "enable_price_vs_high", "INTEGER NOT NULL DEFAULT 1")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semaphore_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker_id INTEGER NOT NULL,
                    calculated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticker_id) REFERENCES analyzed_tickers(id) ON DELETE CASCADE
                )
                """
            )

    def _ensure_column(self, conn, table_name: str, column_name: str, column_definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row["name"] for row in rows}
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_semaphore_snapshots_ticker_calculated_at
                ON semaphore_snapshots (ticker_id, calculated_at DESC)
                """
            )

    def save_semaphore_config(self, config: "SemaphoreConfig") -> int:
        with self._connect() as conn:
            current = conn.execute(
                """
                SELECT last_calculated_at, last_result_json
                FROM semaphore_configs
                WHERE ticker_id = ?
                """,
                (config.ticker_id,),
            ).fetchone()
            last_calculated_at = config.last_calculated_at
            last_result_json = config.last_result_json
            if current is not None:
                if last_calculated_at is None:
                    last_calculated_at = _parse_dt(current["last_calculated_at"])
                if last_result_json is None:
                    last_result_json = current["last_result_json"]

            cursor = conn.execute(
                """
                INSERT INTO semaphore_configs (
                    ticker_id,
                    enable_price_vs_ema10,
                    enable_price_vs_ema20,
                    enable_price_vs_ema100,
                    enable_ema10_vs_ema20,
                    enable_price_vs_high,
                    last_calculated_at,
                    last_result_json,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker_id) DO UPDATE SET
                    enable_price_vs_ema10 = excluded.enable_price_vs_ema10,
                    enable_price_vs_ema20 = excluded.enable_price_vs_ema20,
                    enable_price_vs_ema100 = excluded.enable_price_vs_ema100,
                    enable_ema10_vs_ema20 = excluded.enable_ema10_vs_ema20,
                    enable_price_vs_high = excluded.enable_price_vs_high,
                    updated_at = excluded.updated_at
                """,
                (
                    config.ticker_id,
                    int(config.enable_price_vs_ema10),
                    int(config.enable_price_vs_ema20),
                    int(config.enable_price_vs_ema100),
                    int(config.enable_ema10_vs_ema20),
                    int(config.enable_price_vs_high),
                    last_calculated_at.isoformat(timespec="minutes") if last_calculated_at else None,
                    last_result_json,
                    datetime.now(timezone.utc).isoformat(timespec="minutes"),
                ),
            )
            return int(cursor.lastrowid or config.ticker_id)

    def get_semaphore_config(self, ticker_id: int) -> Optional["SemaphoreConfig"]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, ticker_id, enable_price_vs_ema10, enable_price_vs_ema20,
                       enable_price_vs_ema100, enable_ema10_vs_ema20, enable_price_vs_high,
                       last_calculated_at, last_result_json
                FROM semaphore_configs
                WHERE ticker_id = ?
                """,
                (ticker_id,),
            ).fetchone()

        if not row:
            return None

        return SemaphoreConfig(
            id=int(row["id"]),
            ticker_id=int(row["ticker_id"]),
            enable_price_vs_ema10=bool(row["enable_price_vs_ema10"]),
            enable_price_vs_ema20=bool(row["enable_price_vs_ema20"]),
            enable_price_vs_ema100=bool(row["enable_price_vs_ema100"]),
            enable_ema10_vs_ema20=bool(row["enable_ema10_vs_ema20"]),
            enable_price_vs_high=bool(row["enable_price_vs_high"]),
            last_calculated_at=_parse_dt(row["last_calculated_at"]),
            last_result_json=row["last_result_json"],
        )

    def get_semaphore_config_by_identity(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
    ) -> Optional["SemaphoreConfig"]:
        ticker_id = self.get_ticker_id(symbol, market, timeframe)
        if ticker_id is None:
            return None
        return self.get_semaphore_config(ticker_id)

    def list_semaphore_configs(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.ticker_id, s.enable_price_vs_ema10, s.enable_price_vs_ema20,
                       s.enable_price_vs_ema100, s.enable_ema10_vs_ema20, s.enable_price_vs_high, s.last_calculated_at,
                       s.last_result_json, t.symbol, t.market, t.asset_type, t.timeframe, t.is_active
                FROM semaphore_configs s
                JOIN analyzed_tickers t ON t.id = s.ticker_id
                ORDER BY t.symbol ASC, t.market ASC, t.timeframe ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def save_semaphore_snapshot(self, ticker_id: int, calculated_at: datetime, payload: dict) -> int:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO semaphore_snapshots (ticker_id, calculated_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (ticker_id, calculated_at.isoformat(timespec="minutes"), payload_json),
            )
            current = conn.execute(
                """
                SELECT enable_price_vs_ema10, enable_price_vs_ema20, enable_price_vs_ema100,
                       enable_ema10_vs_ema20, enable_price_vs_high
                FROM semaphore_configs
                WHERE ticker_id = ?
                """,
                (ticker_id,),
            ).fetchone()
            if current is None:
                current = {
                    "enable_price_vs_ema10": 1,
                    "enable_price_vs_ema20": 1,
                    "enable_price_vs_ema100": 1,
                    "enable_ema10_vs_ema20": 1,
                    "enable_price_vs_high": 1,
                }
            conn.execute(
                """
                INSERT INTO semaphore_configs (
                    ticker_id, enable_price_vs_ema10, enable_price_vs_ema20,
                    enable_price_vs_ema100, enable_ema10_vs_ema20, enable_price_vs_high,
                    last_calculated_at, last_result_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker_id) DO UPDATE SET
                    enable_price_vs_ema10 = excluded.enable_price_vs_ema10,
                    enable_price_vs_ema20 = excluded.enable_price_vs_ema20,
                    enable_price_vs_ema100 = excluded.enable_price_vs_ema100,
                    enable_ema10_vs_ema20 = excluded.enable_ema10_vs_ema20,
                    enable_price_vs_high = excluded.enable_price_vs_high,
                    last_calculated_at = excluded.last_calculated_at,
                    last_result_json = excluded.last_result_json,
                    updated_at = excluded.updated_at
                """,
                (
                    ticker_id,
                    int(current["enable_price_vs_ema10"]),
                    int(current["enable_price_vs_ema20"]),
                    int(current["enable_price_vs_ema100"]),
                    int(current["enable_ema10_vs_ema20"]),
                    int(current["enable_price_vs_high"]),
                    calculated_at.isoformat(timespec="minutes"),
                    payload_json,
                    datetime.now(timezone.utc).isoformat(timespec="minutes"),
                ),
            )
            return int(cursor.lastrowid)

    def get_latest_semaphore_snapshot(self, ticker_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT calculated_at, payload_json
                FROM semaphore_snapshots
                WHERE ticker_id = ?
                ORDER BY calculated_at DESC
                LIMIT 1
                """,
                (ticker_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "calculated_at": row["calculated_at"],
            "payload": json.loads(row["payload_json"]),
        }


@dataclass(frozen=True)
class SemaphoreConfig:
    ticker_id: int
    enable_price_vs_ema10: bool = True
    enable_price_vs_ema20: bool = True
    enable_price_vs_ema100: bool = True
    enable_ema10_vs_ema20: bool = True
    enable_price_vs_high: bool = True
    last_calculated_at: Optional[datetime] = None
    last_result_json: Optional[str] = None
    id: Optional[int] = None

    def __post_init__(self) -> None:
        if not any(
            (
                self.enable_price_vs_ema10,
                self.enable_price_vs_ema20,
                self.enable_price_vs_ema100,
                self.enable_ema10_vs_ema20,
                self.enable_price_vs_high,
            )
        ):
            raise ValueError("At least one semaphore indicator must be enabled")

    def to_payload(self) -> dict:
        return {
            "id": self.id,
            "ticker_id": self.ticker_id,
            "enable_price_vs_ema10": self.enable_price_vs_ema10,
            "enable_price_vs_ema20": self.enable_price_vs_ema20,
            "enable_price_vs_ema100": self.enable_price_vs_ema100,
            "enable_ema10_vs_ema20": self.enable_ema10_vs_ema20,
            "enable_price_vs_high": self.enable_price_vs_high,
            "last_calculated_at": self.last_calculated_at.isoformat(timespec="minutes") if self.last_calculated_at else None,
        }


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


class SemaphoreService:
    """Compute and persist the current traffic-light state for a ticker."""

    def __init__(
        self,
        history_service: Optional[HistoricalMarketDataService] = None,
        repository: Optional[SemaphoreRepository] = None,
    ) -> None:
        self.repository = repository or SemaphoreRepository("market_history.sqlite")
        self.history_service = history_service or HistoricalMarketDataService(
            provider=YFinanceMarketDataProvider(),
            repository=self.repository,
        )

    def save_config(self, ticker: AnalyzedTicker, config: SemaphoreConfig) -> SemaphoreConfig:
        ticker_id = self._ensure_ticker_id(ticker)
        stored = SemaphoreConfig(
            ticker_id=ticker_id,
            enable_price_vs_ema10=config.enable_price_vs_ema10,
            enable_price_vs_ema20=config.enable_price_vs_ema20,
            enable_price_vs_ema100=config.enable_price_vs_ema100,
            enable_ema10_vs_ema20=config.enable_ema10_vs_ema20,
            enable_price_vs_high=config.enable_price_vs_high,
            last_calculated_at=config.last_calculated_at,
            last_result_json=config.last_result_json,
            id=config.id,
        )
        saved_id = self.repository.save_semaphore_config(stored)
        return SemaphoreConfig(
            ticker_id=ticker_id,
            enable_price_vs_ema10=stored.enable_price_vs_ema10,
            enable_price_vs_ema20=stored.enable_price_vs_ema20,
            enable_price_vs_ema100=stored.enable_price_vs_ema100,
            enable_ema10_vs_ema20=stored.enable_ema10_vs_ema20,
            enable_price_vs_high=stored.enable_price_vs_high,
            last_calculated_at=stored.last_calculated_at,
            last_result_json=stored.last_result_json,
            id=saved_id,
        )

    def get_config(self, ticker: AnalyzedTicker) -> Optional[SemaphoreConfig]:
        ticker_id = self.repository.get_ticker_id(ticker.symbol, ticker.market, ticker.timeframe)
        if ticker_id is None:
            return None
        return self.repository.get_semaphore_config(ticker_id)

    def calculate(
        self,
        ticker: AnalyzedTicker,
        persist_missing: bool = True,
    ) -> dict:
        ticker = self._normalize_ticker(ticker)
        ticker_id = self._ensure_ticker_id(ticker)
        config = self.repository.get_semaphore_config(ticker_id)
        if config is None:
            raise SemaphoreConfigNotFoundError(
                f"No semaphore config found for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        bars = self._load_bars(ticker, config, persist_missing=persist_missing)
        if not bars:
            raise SemaphoreNoHistoricalDataError(
                f"No historical data available for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        closes = [bar.close for bar in bars]
        periods = self._required_periods(config)
        min_bars = max(periods) if periods else 20
        if len(closes) < min_bars:
            raise SemaphoreNoHistoricalDataError(
                f"Not enough historical bars for {ticker.symbol}; need at least {min_bars}, got {len(closes)}"
            )

        ema10 = calculateEMA(closes, 10) if 10 in periods else None
        ema20 = calculateEMA(closes, 20) if 20 in periods else None
        ema100 = calculateEMA(closes, 100) if 100 in periods else None
        latest_close = closes[-1]
        prior_high = self._prior_historical_high(bars)

        indicators = {}
        if config.enable_price_vs_ema10:
            indicators["price_vs_ema10"] = self._build_price_state(latest_close, ema10[-1], "ema10")
        if config.enable_price_vs_ema20:
            indicators["price_vs_ema20"] = self._build_price_state(latest_close, ema20[-1], "ema20")
        if config.enable_price_vs_ema100:
            indicators["price_vs_ema100"] = self._build_price_state(latest_close, ema100[-1], "ema100")
        if config.enable_ema10_vs_ema20:
            indicators["ema10_vs_ema20"] = self._build_cross_state(ema10[-1], ema20[-1])
        if config.enable_price_vs_high:
            indicators["price_vs_high"] = self._build_high_state(latest_close, prior_high)

        payload = {
            "ticker": ticker.symbol,
            "market": ticker.market,
            "timeframe": ticker.timeframe,
            "calculated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "last_bar_timestamp": bars[-1].timestamp.isoformat(),
            "indicators": indicators,
        }

        self.repository.save_semaphore_snapshot(
            ticker_id=ticker_id,
            calculated_at=datetime.now(timezone.utc),
            payload=payload,
        )
        return payload

    def calculate_by_identity(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
        asset_type: str = "stock",
        persist_missing: bool = True,
    ) -> dict:
        ticker = AnalyzedTicker(
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            timeframe=timeframe,
            is_active=True,
        )
        return self.calculate(ticker, persist_missing=persist_missing)

    def calculate_all(self, persist_missing: bool = True) -> dict:
        results = {"updated_tickers": 0, "failed_tickers": 0, "errors": []}
        for row in self.repository.list_semaphore_configs():
            ticker = AnalyzedTicker(
                id=row["ticker_id"],
                symbol=row["symbol"],
                market=row["market"],
                asset_type=row["asset_type"],
                timeframe=row["timeframe"],
                is_active=bool(row.get("is_active", 1)),
            )
            try:
                self.calculate(ticker, persist_missing=persist_missing)
                results["updated_tickers"] += 1
            except Exception as exc:
                results["failed_tickers"] += 1
                results["errors"].append(f"{ticker.symbol}|{ticker.market}|{ticker.timeframe}: {exc}")
        return results

    def calculate_for_identity(self, symbol: str, market: str, timeframe: str = "1D", asset_type: str = "stock") -> dict:
        return self.calculate_by_identity(symbol, market, timeframe=timeframe, asset_type=asset_type)

    def get_last_calculated_at(self, ticker: AnalyzedTicker) -> Optional[datetime]:
        config = self.get_config(ticker)
        return config.last_calculated_at if config else None

    def get_latest_snapshot(self, ticker: AnalyzedTicker) -> Optional[dict]:
        ticker_id = self.repository.get_ticker_id(ticker.symbol, ticker.market, ticker.timeframe)
        if ticker_id is None:
            return None
        return self.repository.get_latest_semaphore_snapshot(ticker_id)

    def _normalize_ticker(self, ticker: AnalyzedTicker) -> AnalyzedTicker:
        if ticker.timeframe != "1D":
            raise SemaphoreServiceError("Only daily timeframe (1D) is supported for semaphore calculations")
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

    def _required_periods(self, config: SemaphoreConfig) -> List[int]:
        periods = []
        if config.enable_price_vs_ema10 or config.enable_ema10_vs_ema20:
            periods.append(10)
        if config.enable_price_vs_ema20 or config.enable_ema10_vs_ema20:
            periods.append(20)
        if config.enable_price_vs_ema100:
            periods.append(100)
        return sorted(set(periods))

    @staticmethod
    def _prior_historical_high(bars: Sequence[OHLCBar]) -> float:
        if len(bars) < 2:
            raise SemaphoreNoHistoricalDataError("Need at least two bars to compare against the historical high")
        prior_high = max(bar.high for bar in bars[:-1])
        if prior_high <= 0:
            raise SemaphoreNoHistoricalDataError("Historical high is not available")
        return prior_high

    def _load_bars(self, ticker: AnalyzedTicker, config: SemaphoreConfig, persist_missing: bool = True) -> List[OHLCBar]:
        bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
        if bars:
            required_periods = self._required_periods(config)
            min_bars = max(required_periods) if required_periods else 20
            if len(bars) < min_bars and persist_missing:
                lookback_days = max(180, min_bars * 3)
                end_date = datetime.now(timezone.utc).date()
                start_date = end_date - timedelta(days=lookback_days)
                fetched = self.history_service.investigate(
                    ticker,
                    start_date=start_date,
                    end_date=end_date,
                )
                if fetched:
                    self.history_service.save_ticker_bars(ticker, fetched)
                    bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
            if persist_missing:
                ticker_row = self._ticker_row(ticker)
                self.history_service.sync_missing_for_ticker(ticker_row)
                bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
            return bars

        lookback_days = max(180, max(self._required_periods(config) or [20]) * 3)
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=lookback_days)
        bars = self.history_service.investigate(
            ticker,
            start_date=start_date,
            end_date=end_date,
        )
        if bars and persist_missing:
            self.history_service.save_ticker_bars(ticker, bars)
        return bars

    def _ticker_row(self, ticker: AnalyzedTicker) -> dict:
        return {
            "id": ticker.id or self.repository.get_ticker_id(ticker.symbol, ticker.market, ticker.timeframe),
            "symbol": ticker.symbol,
            "market": ticker.market,
            "asset_type": ticker.asset_type,
            "timeframe": ticker.timeframe,
            "is_active": int(ticker.is_active),
        }

    @staticmethod
    def _build_price_state(price: float, ema_value: Optional[float], label: str) -> dict:
        if ema_value is None:
            raise SemaphoreNoHistoricalDataError(f"Not enough data to compute {label}")
        is_green = price > ema_value
        return {
            "state": "green" if is_green else "red",
            "enabled": True,
            "price": price,
            "ema": ema_value,
            "label": label,
        }

    @staticmethod
    def _build_cross_state(ema_fast: Optional[float], ema_slow: Optional[float]) -> dict:
        if ema_fast is None or ema_slow is None:
            raise SemaphoreNoHistoricalDataError("Not enough data to compute EMA10/EMA20 state")
        is_green = ema_fast > ema_slow
        return {
            "state": "green" if is_green else "red",
            "enabled": True,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "label": "ema10_vs_ema20",
        }

    @staticmethod
    def _build_high_state(price: float, historical_high: float) -> dict:
        difference_pct = ((price / historical_high) - 1.0) * 100.0
        return {
            "state": "green" if price > historical_high else "red",
            "enabled": True,
            "price": price,
            "historical_high": historical_high,
            "difference_pct": difference_pct,
            "label": "price_vs_high",
        }


EXAMPLE_TICKER = AnalyzedTicker(
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)


def example_usage() -> dict:
    """Example calculation using mock data and a persisted semaphore config."""
    repo = SemaphoreRepository("semaphore_example.sqlite")
    service = SemaphoreService(
        history_service=HistoricalMarketDataService(provider=MockMarketDataProvider(), repository=repo),
        repository=repo,
    )
    ticker_id = repo.get_or_create_ticker_id(
        symbol=EXAMPLE_TICKER.symbol,
        market=EXAMPLE_TICKER.market,
        asset_type=EXAMPLE_TICKER.asset_type,
        timeframe=EXAMPLE_TICKER.timeframe,
        is_active=EXAMPLE_TICKER.is_active,
    )
    repo.save_semaphore_config(
        SemaphoreConfig(
            ticker_id=ticker_id,
            enable_price_vs_ema10=True,
            enable_price_vs_ema20=True,
            enable_price_vs_ema100=True,
            enable_ema10_vs_ema20=True,
        )
    )
    return service.calculate(EXAMPLE_TICKER, persist_missing=True)
