from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class AdjustedBar:
    trade_date: date
    # Raw OHLC exactly as stored: split-adjusted by the provider, NOT dividend-adjusted
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    # Total-return adjustment: multiply any raw price by adj_factor
    # can adjust open/high/low consistently without a second query
    adj_factor: Decimal
    adj_close: Decimal  # close * adj_factor
