"""Rule primitives for evaluating investment alerts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from analysis_models import AnalyzedTicker
from market_history_service import OHLCBar
from utils import calculateEMA


class AlertRuleError(Exception):
    """Base exception for rule evaluation errors."""


class InvalidAlertRuleError(AlertRuleError):
    """Raised when a rule spec is invalid."""


class NoHistoricalDataError(AlertRuleError):
    """Raised when no OHLC data is available."""


class InsufficientHistoricalDataError(AlertRuleError):
    """Raised when there are not enough bars for the requested rule."""


class UnsupportedTimeframeError(AlertRuleError):
    """Raised when a rule is used with an unsupported timeframe."""


@dataclass
class AlertContext:
    """Snapshot used by alert rules during evaluation."""

    ticker: AnalyzedTicker
    bars: List[OHLCBar]
    closes: List[float]
    ema_cache: Dict[int, List[Optional[float]]] = field(default_factory=dict)

    @classmethod
    def from_bars(cls, ticker: AnalyzedTicker, bars: Sequence[OHLCBar]) -> "AlertContext":
        bars_list = list(bars)
        if not bars_list:
            raise NoHistoricalDataError(
                f"No historical data available for {ticker.symbol} on {ticker.market} ({ticker.timeframe})"
            )
        closes = [bar.close for bar in bars_list]
        return cls(ticker=ticker, bars=bars_list, closes=closes)

    @property
    def latest_bar(self) -> OHLCBar:
        return self.bars[-1]

    @property
    def previous_bar(self) -> Optional[OHLCBar]:
        if len(self.bars) < 2:
            return None
        return self.bars[-2]

    @property
    def latest_close(self) -> float:
        return self.closes[-1]

    @property
    def previous_close(self) -> Optional[float]:
        if len(self.closes) < 2:
            return None
        return self.closes[-2]

    def ema(self, period: int) -> List[Optional[float]]:
        if period not in self.ema_cache:
            self.ema_cache[period] = calculateEMA(self.closes, period)
        return self.ema_cache[period]


@dataclass
class RuleEvaluation:
    """Structured result for a single rule evaluation."""

    rule_id: str
    kind: str
    matched: bool
    timestamp: datetime
    signal: Optional[str] = None
    rule_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    children: List["RuleEvaluation"] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "kind": self.kind,
            "matched": self.matched,
            "signal": self.signal,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "children": [child.to_dict() for child in self.children],
        }

    def to_alert(self, ticker: AnalyzedTicker) -> Dict[str, Any]:
        if not self.matched:
            raise ValueError("Cannot build alert payload from an unmatched rule")
        return {
            "ticker": ticker.symbol,
            "market": ticker.market,
            "timeframe": ticker.timeframe,
            "type": self.kind,
            "signal": self.signal,
            "timestamp": self.timestamp.isoformat(),
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "details": self.details,
        }


@dataclass
class AlertRule(ABC):
    """Base class for all alert rules."""

    rule_id: str
    name: Optional[str] = None
    signal: Optional[str] = None

    @property
    @abstractmethod
    def kind(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, context: AlertContext) -> RuleEvaluation:
        raise NotImplementedError

    def _resolved_signal(self, fallback: Optional[str] = None) -> Optional[str]:
        return self.signal or fallback


@dataclass
class PriceThresholdRule(AlertRule):
    """Trigger when the last close is above or below a threshold."""

    threshold: float = 0.0
    comparator: str = "gt"

    @property
    def kind(self) -> str:
        return "price_threshold"

    def __post_init__(self) -> None:
        self.comparator = self.comparator.lower().strip()
        if self.comparator not in {"gt", "gte", "lt", "lte", "eq"}:
            raise InvalidAlertRuleError("comparator must be one of gt, gte, lt, lte, eq")

    def evaluate(self, context: AlertContext) -> RuleEvaluation:
        current_price = context.latest_close
        matched = False
        fallback_signal = None

        if self.comparator == "gt":
            matched = current_price > self.threshold
            fallback_signal = "bullish"
        elif self.comparator == "gte":
            matched = current_price >= self.threshold
            fallback_signal = "bullish"
        elif self.comparator == "lt":
            matched = current_price < self.threshold
            fallback_signal = "bearish"
        elif self.comparator == "lte":
            matched = current_price <= self.threshold
            fallback_signal = "bearish"
        elif self.comparator == "eq":
            matched = current_price == self.threshold

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            kind=self.kind,
            matched=matched,
            signal=self._resolved_signal(fallback_signal) if matched else None,
            timestamp=context.latest_bar.timestamp,
            details={
                "threshold": self.threshold,
                "comparator": self.comparator,
                "current_price": current_price,
            },
        )


@dataclass
class PriceCrossEMARule(AlertRule):
    """Trigger when the price crosses an EMA on the latest bar."""

    ema_period: int = 20
    direction: str = "both"

    @property
    def kind(self) -> str:
        return "price_cross_ema"

    def __post_init__(self) -> None:
        if not isinstance(self.ema_period, int) or self.ema_period <= 0:
            raise InvalidAlertRuleError("ema_period must be a positive integer")
        self.direction = self.direction.lower().strip()
        if self.direction not in {"both", "bullish", "bearish"}:
            raise InvalidAlertRuleError("direction must be one of both, bullish, bearish")

    def evaluate(self, context: AlertContext) -> RuleEvaluation:
        if len(context.closes) < self.ema_period + 1:
            raise InsufficientHistoricalDataError(
                f"Need at least {self.ema_period + 1} closing prices to evaluate EMA{self.ema_period} crossover"
            )

        ema = context.ema(self.ema_period)
        if ema[-2] is None or ema[-1] is None:
            raise InsufficientHistoricalDataError(
                f"Need enough data to evaluate EMA{self.ema_period} crossover for {context.ticker.symbol}"
            )

        prev_close = context.previous_close
        curr_close = context.latest_close
        prev_ema = ema[-2]
        curr_ema = ema[-1]

        bullish = prev_close is not None and prev_close <= prev_ema and curr_close > curr_ema
        bearish = prev_close is not None and prev_close >= prev_ema and curr_close < curr_ema

        matched = False
        signal = None
        if bullish and self.direction in {"both", "bullish"}:
            matched = True
            signal = self._resolved_signal("bullish")
        elif bearish and self.direction in {"both", "bearish"}:
            matched = True
            signal = self._resolved_signal("bearish")

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            kind=self.kind,
            matched=matched,
            signal=signal,
            timestamp=context.latest_bar.timestamp,
            details={
                "ema_period": self.ema_period,
                "direction": self.direction,
                "previous_close": prev_close,
                "current_close": curr_close,
                "previous_ema": prev_ema,
                "current_ema": curr_ema,
            },
        )


@dataclass
class EMACrossRule(AlertRule):
    """Trigger when a fast EMA crosses a slow EMA on the latest bar."""

    fast_period: int = 10
    slow_period: int = 20
    direction: str = "both"

    @property
    def kind(self) -> str:
        return "ema_cross"

    def __post_init__(self) -> None:
        if not isinstance(self.fast_period, int) or self.fast_period <= 0:
            raise InvalidAlertRuleError("fast_period must be a positive integer")
        if not isinstance(self.slow_period, int) or self.slow_period <= 0:
            raise InvalidAlertRuleError("slow_period must be a positive integer")
        if self.fast_period >= self.slow_period:
            raise InvalidAlertRuleError("fast_period must be lower than slow_period")
        self.direction = self.direction.lower().strip()
        if self.direction not in {"both", "bullish", "bearish"}:
            raise InvalidAlertRuleError("direction must be one of both, bullish, bearish")

    def evaluate(self, context: AlertContext) -> RuleEvaluation:
        if len(context.closes) < self.slow_period + 1:
            raise InsufficientHistoricalDataError(
                f"Need at least {self.slow_period + 1} closing prices to evaluate EMA{self.fast_period}/EMA{self.slow_period} crossover"
            )

        fast = context.ema(self.fast_period)
        slow = context.ema(self.slow_period)
        if fast[-2] is None or fast[-1] is None or slow[-2] is None or slow[-1] is None:
            raise InsufficientHistoricalDataError(
                f"Need enough data to evaluate EMA{self.fast_period}/EMA{self.slow_period} crossover for {context.ticker.symbol}"
            )

        prev_diff = fast[-2] - slow[-2]
        curr_diff = fast[-1] - slow[-1]

        bullish = prev_diff <= 0 and curr_diff > 0
        bearish = prev_diff >= 0 and curr_diff < 0

        matched = False
        signal = None
        if bullish and self.direction in {"both", "bullish"}:
            matched = True
            signal = self._resolved_signal("bullish")
        elif bearish and self.direction in {"both", "bearish"}:
            matched = True
            signal = self._resolved_signal("bearish")

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            kind=self.kind,
            matched=matched,
            signal=signal,
            timestamp=context.latest_bar.timestamp,
            details={
                "fast_period": self.fast_period,
                "slow_period": self.slow_period,
                "direction": self.direction,
                "previous_fast_ema": fast[-2],
                "current_fast_ema": fast[-1],
                "previous_slow_ema": slow[-2],
                "current_slow_ema": slow[-1],
            },
        )


@dataclass
class CompositeRule(AlertRule):
    """Combine other rules using all/any/not logic."""

    operator: str = "all"
    rules: List[AlertRule] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return "group"

    def __post_init__(self) -> None:
        self.operator = self.operator.lower().strip()
        if self.operator not in {"all", "any", "not"}:
            raise InvalidAlertRuleError("operator must be one of all, any, not")
        if not self.rules:
            raise InvalidAlertRuleError("rules cannot be empty")
        if self.operator == "not" and len(self.rules) != 1:
            raise InvalidAlertRuleError("not operator requires exactly one rule")

    def evaluate(self, context: AlertContext) -> RuleEvaluation:
        children = [rule.evaluate(context) for rule in self.rules]
        if self.operator == "all":
            matched = all(child.matched for child in children)
        elif self.operator == "any":
            matched = any(child.matched for child in children)
        else:
            matched = not children[0].matched

        signal = self.signal
        if signal is None and matched:
            child_signals = {child.signal for child in children if child.signal}
            if len(child_signals) == 1:
                signal = child_signals.pop()

        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            kind=self.kind,
            matched=matched,
            signal=signal,
            timestamp=context.latest_bar.timestamp,
            details={
                "operator": self.operator,
                "child_count": len(children),
            },
            children=children,
        )


def build_alert_rule(spec: Dict[str, Any]) -> AlertRule:
    """Build an alert rule tree from a dictionary specification."""

    if not isinstance(spec, dict):
        raise InvalidAlertRuleError("spec must be a dictionary")

    kind = str(spec.get("kind", "")).strip().lower()
    rule_id = str(spec.get("id") or spec.get("rule_id") or "").strip()
    if not rule_id:
        raise InvalidAlertRuleError("spec must include id or rule_id")
    name = spec.get("name")
    signal = spec.get("signal")

    if kind == "price_threshold":
        return PriceThresholdRule(
            rule_id=rule_id,
            name=name,
            signal=signal,
            threshold=float(spec["threshold"]),
            comparator=str(spec.get("comparator", "gt")),
        )

    if kind == "price_cross_ema":
        return PriceCrossEMARule(
            rule_id=rule_id,
            name=name,
            signal=signal,
            ema_period=int(spec["ema_period"]),
            direction=str(spec.get("direction", "both")),
        )

    if kind == "ema_cross":
        return EMACrossRule(
            rule_id=rule_id,
            name=name,
            signal=signal,
            fast_period=int(spec["fast_period"]),
            slow_period=int(spec["slow_period"]),
            direction=str(spec.get("direction", "both")),
        )

    if kind in {"group", "all", "any", "not"}:
        operator = str(spec.get("operator", kind)).strip().lower()
        child_specs = spec.get("rules", [])
        if not isinstance(child_specs, list):
            raise InvalidAlertRuleError("group rules must be a list")
        child_rules = [build_alert_rule(child_spec) for child_spec in child_specs]
        return CompositeRule(
            rule_id=rule_id,
            name=name,
            signal=signal,
            operator=operator,
            rules=child_rules,
        )

    raise InvalidAlertRuleError(f"Unsupported rule kind: {kind}")
