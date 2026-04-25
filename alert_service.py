"""Rule-based alert evaluation service."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence

from analysis_models import AnalyzedTicker
from alert_rules import (
    AlertContext,
    AlertRule,
    AlertRuleError,
    CompositeRule,
    EMACrossRule,
    InsufficientHistoricalDataError,
    InvalidAlertRuleError,
    NoHistoricalDataError,
    PriceCrossEMARule,
    PriceThresholdRule,
    RuleEvaluation,
    UnsupportedTimeframeError,
    build_alert_rule,
)
from market_history_service import (
    HistoricalMarketDataService,
    MockMarketDataProvider,
    OHLCBar,
    SqliteMarketHistoryRepository,
    YFinanceMarketDataProvider,
)


class RuleBasedAlertService:
    """Evaluate one or more alert rules for a ticker."""

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
        rules: Sequence[AlertRule],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        persist_missing: bool = True,
    ) -> List[dict]:
        ticker = self._normalize_ticker(ticker)
        context = self._load_context(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            persist_missing=persist_missing,
        )

        alerts: List[dict] = []
        for rule in rules:
            evaluation = rule.evaluate(context)
            if evaluation.matched:
                alerts.append(evaluation.to_alert(ticker))
        return alerts

    def evaluate_one(
        self,
        ticker: AnalyzedTicker,
        rule: AlertRule,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        persist_missing: bool = True,
    ) -> Optional[dict]:
        alerts = self.evaluate(
            ticker=ticker,
            rules=[rule],
            start_date=start_date,
            end_date=end_date,
            persist_missing=persist_missing,
        )
        return alerts[0] if alerts else None

    def evaluate_from_specs(
        self,
        ticker: AnalyzedTicker,
        specs: Sequence[dict],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        persist_missing: bool = True,
    ) -> List[dict]:
        rules = [build_alert_rule(spec) for spec in specs]
        return self.evaluate(
            ticker=ticker,
            rules=rules,
            start_date=start_date,
            end_date=end_date,
            persist_missing=persist_missing,
        )

    def _normalize_ticker(self, ticker: AnalyzedTicker) -> AnalyzedTicker:
        if ticker.timeframe != "1D":
            raise UnsupportedTimeframeError("Only daily timeframe (1D) is supported for alerts")
        return ticker

    def _load_context(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date],
        end_date: Optional[date],
        persist_missing: bool,
    ) -> AlertContext:
        bars = self.repository.load_bars_by_identity(ticker.symbol, ticker.market, ticker.timeframe)
        if not bars:
            effective_end = end_date or datetime.now(timezone.utc).date()
            effective_start = start_date or (effective_end - timedelta(days=90))
            bars = self.history_service.investigate(
                ticker,
                start_date=effective_start,
                end_date=effective_end,
            )
            if bars and persist_missing:
                self.history_service.save_ticker_bars(ticker, bars)

        if not bars:
            raise NoHistoricalDataError(
                f"No historical data available for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )

        if len(bars) < 2:
            raise InsufficientHistoricalDataError(
                f"Need at least two bars to evaluate alerts for {ticker.symbol}"
            )

        return AlertContext.from_bars(ticker, bars)


class EmaCrossAlertService:
    """Compatibility facade for the original EMA10/EMA20 alert contract."""

    def __init__(
        self,
        history_service: Optional[HistoricalMarketDataService] = None,
        repository: Optional[SqliteMarketHistoryRepository] = None,
    ) -> None:
        self._engine = RuleBasedAlertService(history_service=history_service, repository=repository)

    def evaluate(
        self,
        ticker: AnalyzedTicker,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        persist_missing: bool = True,
    ) -> Optional[dict]:
        rule = EMACrossRule(
            rule_id=f"ema_cross_{ticker.symbol}_{ticker.market}_{ticker.timeframe}",
            name="EMA10/EMA20 crossover",
            fast_period=10,
            slow_period=20,
        )
        alert = self._engine.evaluate_one(
            ticker=ticker,
            rule=rule,
            start_date=start_date,
            end_date=end_date,
            persist_missing=persist_missing,
        )
        if alert is None:
            return None
        return {
            "ticker": alert["ticker"],
            "type": alert["type"],
            "signal": alert["signal"],
            "timestamp": alert["timestamp"],
        }


EXAMPLE_TICKER = AnalyzedTicker(
    symbol="AAPL",
    market="NYSE",
    asset_type="stock",
    timeframe="1D",
    is_active=True,
)


def example_usage() -> List[dict]:
    """Example using the mock provider and a mixed rule set."""
    repo = SqliteMarketHistoryRepository("alert_example.sqlite")
    service = RuleBasedAlertService(
        history_service=HistoricalMarketDataService(
            provider=MockMarketDataProvider(),
            repository=repo,
        ),
        repository=repo,
    )

    rules = [
        PriceThresholdRule(
            rule_id="price_over_30",
            name="Close above 30",
            threshold=30,
            comparator="gt",
            signal="bullish",
        ),
        CompositeRule(
            rule_id="bullish_combo",
            name="Price above threshold and EMA crossover",
            signal="bullish",
            operator="all",
            rules=[
                PriceThresholdRule(
                    rule_id="price_over_30_inner",
                    threshold=30,
                    comparator="gt",
                    signal="bullish",
                ),
                PriceCrossEMARule(
                    rule_id="price_cross_ema20",
                    ema_period=20,
                ),
            ],
        ),
    ]
    return service.evaluate(EXAMPLE_TICKER, rules, persist_missing=True)


__all__ = [
    "AlertRuleError",
    "CompositeRule",
    "EmaCrossAlertService",
    "EXAMPLE_TICKER",
    "InsufficientHistoricalDataError",
    "InvalidAlertRuleError",
    "NoHistoricalDataError",
    "PriceCrossEMARule",
    "PriceThresholdRule",
    "RuleBasedAlertService",
    "UnsupportedTimeframeError",
    "build_alert_rule",
    "example_usage",
]
