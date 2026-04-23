"""Historical OHLC market data service with provider abstraction and SQLite persistence."""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Protocol, Sequence

from analysis_models import AnalyzedTicker
import yfinance as yf


def _is_nan(value) -> bool:
    try:
        return math.isnan(float(value))
    except Exception:
        return False


@dataclass(frozen=True)
class OHLCBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("timestamp must be a datetime")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=timezone.utc))
        for field_name in ("open", "high", "low", "close", "volume"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{field_name} must be numeric")
        if self.low > self.high:
            raise ValueError("low cannot be greater than high")

    def to_row(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }


class MarketDataProvider(Protocol):
    def get_historical_ohlc(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OHLCBar]:
        """Return historical OHLC bars for the requested instrument."""


class MockMarketDataProvider:
    """Deterministic mock provider for local development and tests."""

    def get_historical_ohlc(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OHLCBar]:
        if timeframe != "1D":
            raise ValueError("Mock provider currently supports only daily timeframe")

        start = start_date or (datetime.now(timezone.utc).date() - timedelta(days=30))
        end = end_date or datetime.now(timezone.utc).date()
        if start > end:
            raise ValueError("start_date cannot be after end_date")

        seed = f"{symbol.upper()}:{market.upper()}:{timeframe}"
        base = self._seed_price(seed)
        bars: List[OHLCBar] = []
        current = start
        idx = 0
        while current <= end:
            drift = math.sin(idx / 3.5) * 1.8
            trend = idx * 0.12
            close = round(base + drift + trend, 2)
            open_ = round(close - 0.45, 2)
            high = round(max(open_, close) + 0.9, 2)
            low = round(min(open_, close) - 0.8, 2)
            volume = float(1_000_000 + idx * 12_500 + int(base * 1000))
            bars.append(
                OHLCBar(
                    timestamp=datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )
            current += timedelta(days=1)
            idx += 1
        return bars

    @staticmethod
    def _seed_price(seed: str) -> float:
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        raw = int(digest[:8], 16)
        return 20.0 + (raw % 5000) / 100.0


class YFinanceMarketDataProvider:
    """Real market data provider using yfinance with a project-local cache."""

    def __init__(self, cache_dir: Optional[str] = None) -> None:
        base_dir = Path(cache_dir) if cache_dir else Path(__file__).resolve().parent / ".yfinance_cache"
        base_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(base_dir))
        self.cache_dir = base_dir

    def get_historical_ohlc(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OHLCBar]:
        if timeframe != "1D":
            raise ValueError("YFinance provider currently supports only daily timeframe")

        ticker = self._resolve_ticker(symbol, market)
        start = start_date or (datetime.now(timezone.utc).date() - timedelta(days=30))
        end = end_date or datetime.now(timezone.utc).date()
        if start > end:
            raise ValueError("start_date cannot be after end_date")

        # yfinance end date is exclusive for history downloads
        df = yf.Ticker(ticker).history(
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            auto_adjust=False,
            actions=False,
        )
        if df.empty:
            return []

        bars: List[OHLCBar] = []
        for ts, row in df.iterrows():
            ts_utc = ts.to_pydatetime()
            if ts_utc.tzinfo is None:
                ts_utc = ts_utc.replace(tzinfo=timezone.utc)
            else:
                ts_utc = ts_utc.astimezone(timezone.utc)

            bars.append(
                OHLCBar(
                    timestamp=ts_utc,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"]) if not _is_nan(row["Volume"]) else 0.0,
                )
            )
        return bars

    @staticmethod
    def _resolve_ticker(symbol: str, market: str) -> str:
        symbol = symbol.strip().upper()
        market = market.strip().upper()

        if market in {"CRYPTO", "BINANCE"} or symbol in {"BTC", "ETH", "SOL", "LTC", "XRP", "ADA"}:
            if symbol.endswith("-USD"):
                return symbol
            return f"{symbol}-USD"

        if market == "BYMA" or symbol.endswith(".BA"):
            return symbol if symbol.endswith(".BA") else f"{symbol}.BA"

        return symbol


class SqliteMarketHistoryRepository:
    """Simple SQLite persistence layer for OHLC history."""

    def __init__(self, db_path: str = "market_history.sqlite") -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyzed_tickers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    market TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, market, timeframe)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_ohlc_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker_id INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'mock',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker_id, timestamp)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_ohlc_history_ticker_ts
                ON market_ohlc_history (ticker_id, timestamp)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def get_or_create_ticker_id(
        self,
        symbol: str,
        market: str,
        asset_type: str = "stock",
        timeframe: str = "1D",
        is_active: bool = True,
    ) -> int:
        symbol = symbol.strip().upper()
        market = market.strip().upper()
        asset_type = asset_type.strip().lower()
        timeframe = timeframe.strip().upper()

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM analyzed_tickers
                WHERE symbol = ? AND market = ? AND timeframe = ?
                """,
                (symbol, market, timeframe),
            ).fetchone()
            if row:
                return int(row["id"])

            cursor = conn.execute(
                """
                INSERT INTO analyzed_tickers (
                    symbol, market, asset_type, timeframe, is_active
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (symbol, market, asset_type, timeframe, int(is_active)),
            )
            return int(cursor.lastrowid)

    def list_tickers(self) -> List[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, market, asset_type, timeframe, is_active, created_at
                FROM analyzed_tickers
                ORDER BY symbol ASC, market ASC, timeframe ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def get_ticker_id(self, symbol: str, market: str, timeframe: str = "1D") -> Optional[int]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id
                FROM analyzed_tickers
                WHERE symbol = ? AND market = ? AND timeframe = ?
                """,
                (symbol.strip().upper(), market.strip().upper(), timeframe.strip().upper()),
            ).fetchone()
        return int(row["id"]) if row else None

    def save_bars(self, ticker_id: int, bars: Sequence[OHLCBar], source: str = "mock") -> int:
        if not isinstance(ticker_id, int) or ticker_id <= 0:
            raise ValueError("ticker_id must be a positive integer")
        if not bars:
            return 0

        rows = [
            (
                ticker_id,
                bar.timestamp.isoformat(),
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                float(bar.volume),
                source,
            )
            for bar in bars
        ]

        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO market_ohlc_history (
                    ticker_id, timestamp, open, high, low, close, volume, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker_id, timestamp) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    source = excluded.source
                """,
                rows,
            )
            return len(rows)

    def load_bars(self, ticker_id: int) -> List[OHLCBar]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM market_ohlc_history
                WHERE ticker_id = ?
                ORDER BY timestamp ASC
                """,
                (ticker_id,),
            ).fetchall()

        return [
            OHLCBar(
                timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            for row in rows
        ]

    def load_bars_by_identity(self, symbol: str, market: str, timeframe: str = "1D") -> List[OHLCBar]:
        ticker_id = self.get_ticker_id(symbol, market, timeframe)
        if ticker_id is None:
            return []
        return self.load_bars(ticker_id)

    def get_last_timestamp(self, ticker_id: int) -> Optional[datetime]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT timestamp
                FROM market_ohlc_history
                WHERE ticker_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (ticker_id,),
            ).fetchone()

        if not row:
            return None
        return datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))

    def get_sync_flag(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM sync_metadata WHERE key = ?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    def set_sync_flag(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


class HistoricalMarketDataService:
    """Fetches OHLC data from a provider and stores it in the database."""

    def __init__(
        self,
        provider: MarketDataProvider,
        repository: Optional[SqliteMarketHistoryRepository] = None,
    ) -> None:
        self.provider = provider
        self.repository = repository or SqliteMarketHistoryRepository()

    def sync_ticker(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> int:
        if ticker.timeframe != "1D":
            raise ValueError("Only daily timeframe is supported for now")

        ticker_id = ticker.id or self.repository.get_or_create_ticker_id(
            symbol=ticker.symbol,
            market=ticker.market,
            asset_type=ticker.asset_type,
            timeframe=ticker.timeframe,
            is_active=ticker.is_active,
        )

        bars = self.provider.get_historical_ohlc(
            symbol=ticker.symbol,
            market=ticker.market,
            timeframe=ticker.timeframe,
            start_date=start_date,
            end_date=end_date,
        )
        return self.repository.save_bars(ticker_id, bars, source=self._provider_name())

    def sync_by_identity(
        self,
        symbol: str,
        market: str,
        asset_type: str = "stock",
        timeframe: str = "1D",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> int:
        ticker = AnalyzedTicker(
            symbol=symbol,
            market=market,
            asset_type=asset_type,
            timeframe=timeframe,
            is_active=True,
        )
        return self.sync_ticker(ticker, start_date=start_date, end_date=end_date)

    def _provider_name(self) -> str:
        return self.provider.__class__.__name__

    def investigate(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[OHLCBar]:
        if ticker.timeframe != "1D":
            raise ValueError("Only daily timeframe is supported for now")
        return self.provider.get_historical_ohlc(
            symbol=ticker.symbol,
            market=ticker.market,
            timeframe=ticker.timeframe,
            start_date=start_date,
            end_date=end_date,
        )

    def load_registered(
        self,
        symbol: str,
        market: str,
        timeframe: str = "1D",
    ) -> List[OHLCBar]:
        return self.repository.load_bars_by_identity(symbol, market, timeframe)

    def save_ticker_bars(self, ticker: AnalyzedTicker, bars: Sequence[OHLCBar]) -> int:
        if ticker.timeframe != "1D":
            raise ValueError("Only daily timeframe is supported for now")

        ticker_id = ticker.id or self.repository.get_or_create_ticker_id(
            symbol=ticker.symbol,
            market=ticker.market,
            asset_type=ticker.asset_type,
            timeframe=ticker.timeframe,
            is_active=ticker.is_active,
        )
        return self.repository.save_bars(ticker_id, bars, source=self._provider_name())

    def sync_missing_for_ticker(self, ticker_row: dict, end_date: Optional[date] = None) -> int:
        ticker = AnalyzedTicker(
            id=ticker_row.get("id"),
            symbol=ticker_row["symbol"],
            market=ticker_row["market"],
            asset_type=ticker_row.get("asset_type", "stock"),
            timeframe=ticker_row.get("timeframe", "1D"),
            is_active=bool(ticker_row.get("is_active", 1)),
        )

        if ticker.timeframe != "1D":
            return 0

        last_ts = self.repository.get_last_timestamp(ticker.id or 0)
        if last_ts is None:
            start_date = end_date or datetime.now(timezone.utc).date()
            start_date = start_date - timedelta(days=30)
        else:
            start_date = (last_ts.date() + timedelta(days=1))

        effective_end = end_date or datetime.now(timezone.utc).date()
        if start_date > effective_end:
            return 0

        bars = self.provider.get_historical_ohlc(
            symbol=ticker.symbol,
            market=ticker.market,
            timeframe=ticker.timeframe,
            start_date=start_date,
            end_date=effective_end,
        )
        if not bars:
            return 0
        return self.save_ticker_bars(ticker, bars)

    def sync_all_missing(self, end_date: Optional[date] = None) -> dict:
        results = {"updated_tickers": 0, "saved_bars": 0, "failed_tickers": 0, "errors": []}
        for ticker_row in self.repository.list_tickers():
            if not bool(ticker_row.get("is_active", 1)):
                continue
            try:
                saved = self.sync_missing_for_ticker(ticker_row, end_date=end_date)
                if saved > 0:
                    results["updated_tickers"] += 1
                    results["saved_bars"] += saved
            except Exception as exc:
                results["failed_tickers"] += 1
                results["errors"].append(
                    f"{ticker_row.get('symbol')}|{ticker_row.get('market')}|{ticker_row.get('timeframe')}: {exc}"
                )

        self.repository.set_sync_flag("last_update", datetime.now(timezone.utc).isoformat())
        status = f"updated_tickers={results['updated_tickers']};saved_bars={results['saved_bars']};failed_tickers={results['failed_tickers']}"
        if results["errors"]:
            status = status + ";errors=" + " | ".join(results["errors"])
        self.repository.set_sync_flag("last_status", status)
        return results

    def get_last_sync(self) -> str:
        return self.repository.get_sync_flag("last_update", "")

    def get_last_sync_status(self) -> str:
        return self.repository.get_sync_flag("last_status", "")


EXAMPLE_TICKER = AnalyzedTicker(
    id=1,
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)

EXAMPLE_PROVIDER = MockMarketDataProvider()
EXAMPLE_SERVICE = HistoricalMarketDataService(EXAMPLE_PROVIDER)


def example_usage() -> int:
    """Example: fetch and persist one month of daily bars for AAPL."""
    repo = SqliteMarketHistoryRepository()
    service = HistoricalMarketDataService(MockMarketDataProvider(), repo)
    return service.sync_ticker(EXAMPLE_TICKER, start_date=date.today() - timedelta(days=30))
