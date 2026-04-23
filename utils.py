import streamlit as st
from decimal import Decimal, getcontext

getcontext().prec = 28

def safe_float(value):
    """Safely convert string with thousands separators and dot decimal to float"""
    if isinstance(value, (float, int)):
        return float(value)
    if not value or str(value).strip() == "":
        return 0.0
    try:
        s = str(value).strip()
        # If it has both comma and dot, assume US style (comma = thousands, dot = decimal)
        # OR if it has a comma and it appears to be a thousands separator.
        # But safest is: remove all commas, then parse.
        # However, if someone entered "1,50" meaning "1.50", we need to handle that.
        
        # Heuristic: if comma is near the end (2 chars), it might be decimal.
        # But since we use f"{x:,.2f}" for output, we should be careful.
        
        # Simply remove commas and see if it floats.
        clean_s = s.replace(",", "")
        return float(clean_s)
    except ValueError:
        try:
            # Try treating comma as decimal if it failed
            return float(s.replace(",", "."))
        except ValueError:
            return 0.0

def get_secret(key):
    """Safely get a secret from st.secrets to avoid StreamlitSecretNotFoundError.
    Converts proxy objects recursively to plain Python objects to prevent caching recursion issues.
    """
    def _clean(obj):
        if hasattr(obj, "to_dict"):
            return _clean(obj.to_dict())
        if isinstance(obj, dict) or (hasattr(obj, "__getitem__") and hasattr(obj, "keys")):
            return {str(k): _clean(obj[k]) for k in obj.keys()}
        if isinstance(obj, list):
            return [_clean(i) for i in obj]
        return obj

    try:
        val = st.secrets.get(key)
        return _clean(val) if val is not None else None
    except Exception:
        return None


def calculateEMA(prices, period):
    """Calculate an EMA series aligned with the input prices.

    The first EMA value is seeded with the SMA of the first `period` prices.
    Leading values before the seed are returned as None to keep alignment.
    """
    if period is None or period <= 0:
        raise ValueError("period must be a positive integer")
    if prices is None:
        raise ValueError("prices is required")

    values = [Decimal(str(p)) for p in prices]
    if not values:
        return []

    if period > len(values):
        raise ValueError("period cannot be greater than the number of prices")

    ema_values = [None] * len(values)
    multiplier = Decimal("2") / (Decimal(period) + Decimal("1"))

    seed_slice = values[:period]
    seed = sum(seed_slice) / Decimal(period)
    ema_values[period - 1] = float(seed)

    prev_ema = seed
    for idx in range(period, len(values)):
        current = values[idx]
        prev_ema = (current - prev_ema) * multiplier + prev_ema
        ema_values[idx] = float(prev_ema)

    return ema_values


def detectCrossovers(seriesA, seriesB):
    """Detect strict crossovers between two aligned numeric series.

    Returns a list of dicts with:
      - index: the position where the crossover is confirmed
      - type: "bullish" when A crosses above B, "bearish" when A crosses below B

    A crossover is only emitted when the current non-zero difference changes
    sign versus the last observed non-zero difference. Equality by itself does
    not trigger a signal.
    """
    if seriesA is None or seriesB is None:
        raise ValueError("seriesA and seriesB are required")

    if len(seriesA) != len(seriesB):
        raise ValueError("seriesA and seriesB must have the same length")

    if len(seriesA) < 2:
        return []

    def _to_decimal(value):
        if value is None:
            raise ValueError("series values cannot be None")
        return Decimal(str(value))

    events = []
    prev_nonzero_sign = 0

    for idx in range(len(seriesA)):
        curr_diff = _to_decimal(seriesA[idx]) - _to_decimal(seriesB[idx])
        if curr_diff == 0:
            continue

        curr_sign = 1 if curr_diff > 0 else -1
        if prev_nonzero_sign == -1 and curr_sign == 1:
            events.append({"index": idx, "type": "bullish"})
        elif prev_nonzero_sign == 1 and curr_sign == -1:
            events.append({"index": idx, "type": "bearish"})

        prev_nonzero_sign = curr_sign

    return events
