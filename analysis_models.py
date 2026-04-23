"""Data model and validation helpers for investment analysis tickers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Sequence

ALLOWED_ASSET_TYPES = {"stock", "cedear", "bond", "etf", "on"}
ALLOWED_TIMEFRAMES = {"1D", "1W", "1M"}

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")
MARKET_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{1,19}$")


def _normalize_symbol(value: str) -> str:
    if value is None:
        raise ValueError("symbol is required")
    symbol = str(value).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    if not SYMBOL_RE.match(symbol):
        raise ValueError("symbol must contain only uppercase letters, numbers, dots or hyphens")
    return symbol


def _normalize_market(value: str) -> str:
    if value is None:
        raise ValueError("market is required")
    market = str(value).strip().upper()
    if not market:
        raise ValueError("market is required")
    if not MARKET_RE.match(market):
        raise ValueError("market must contain only uppercase letters, numbers, dots or hyphens")
    return market


def _normalize_asset_type(value: str) -> str:
    if value is None:
        raise ValueError("asset_type is required")
    asset_type = str(value).strip().lower()
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise ValueError(f"asset_type must be one of {sorted(ALLOWED_ASSET_TYPES)}")
    return asset_type


def _normalize_timeframe(value: str) -> str:
    if value is None:
        raise ValueError("timeframe is required")
    timeframe = str(value).strip().upper()
    if timeframe not in ALLOWED_TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {sorted(ALLOWED_TIMEFRAMES)}")
    return timeframe


def _normalize_bool(value: bool, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{field_name} must be a boolean")


def _normalize_ema_periods(values: Sequence[int]) -> List[int]:
    if values is None:
        raise ValueError("ema_periods is required")
    if not isinstance(values, (list, tuple)):
        raise ValueError("ema_periods must be a list of integers")
    if not values:
        raise ValueError("ema_periods cannot be empty")

    normalized = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("ema_periods must contain only integers")
        if value <= 0:
            raise ValueError("ema_periods values must be greater than zero")
        normalized.append(value)

    if normalized != sorted(set(normalized)):
        raise ValueError("ema_periods must be unique and sorted ascending")

    return normalized


@dataclass(frozen=True)
class AnalyzedTicker:
    symbol: str
    market: str
    asset_type: str
    timeframe: str
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _normalize_symbol(self.symbol))
        object.__setattr__(self, "market", _normalize_market(self.market))
        object.__setattr__(self, "asset_type", _normalize_asset_type(self.asset_type))
        object.__setattr__(self, "timeframe", _normalize_timeframe(self.timeframe))
        object.__setattr__(self, "is_active", _normalize_bool(self.is_active, "is_active"))

        created_at = self.created_at
        if not isinstance(created_at, datetime):
            raise ValueError("created_at must be a datetime")
        if created_at.tzinfo is None:
            object.__setattr__(self, "created_at", created_at.replace(tzinfo=timezone.utc))

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "market": self.market,
            "asset_type": self.asset_type,
            "timeframe": self.timeframe,
            "is_active": int(self.is_active),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class IndicatorConfig:
    ticker_id: int
    ema_periods: List[int]
    enable_rsi: bool = True
    enable_macd: bool = True
    id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.ticker_id, int) or self.ticker_id <= 0:
            raise ValueError("ticker_id must be a positive integer")
        object.__setattr__(self, "ema_periods", _normalize_ema_periods(self.ema_periods))
        object.__setattr__(self, "enable_rsi", _normalize_bool(self.enable_rsi, "enable_rsi"))
        object.__setattr__(self, "enable_macd", _normalize_bool(self.enable_macd, "enable_macd"))

    def to_row(self) -> dict:
        return {
            "id": self.id,
            "ticker_id": self.ticker_id,
            "ema_periods": json.dumps(self.ema_periods),
            "enable_rsi": int(self.enable_rsi),
            "enable_macd": int(self.enable_macd),
        }


EXAMPLE_TICKER = AnalyzedTicker(
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)

EXAMPLE_INDICATOR_CONFIG = IndicatorConfig(
    ticker_id=1,
    ema_periods=[10, 20, 100],
    enable_rsi=True,
    enable_macd=True,
)


def example_insert_sql() -> str:
    """Return a simple parameterized insert example."""
    return """
INSERT INTO analyzed_tickers (symbol, market, asset_type, timeframe, is_active, created_at)
VALUES (?, ?, ?, ?, ?, ?);

INSERT INTO indicator_configs (ticker_id, ema_periods, enable_rsi, enable_macd)
VALUES (?, ?, ?, ?);
""".strip()
