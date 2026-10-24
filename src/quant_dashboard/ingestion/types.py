from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PriceBar:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal  # split-adjusted, NOT dividend-adjusted (Yahoo's convention)
    adj_close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class Dividend:
    ex_date: date
    amount: Decimal


@dataclass(frozen=True, slots=True)
class Split:
    ex_date: date
    ratio: Decimal


@dataclass(frozen=True, slots=True)
class DailyData:
    symbol: str
    bars: tuple[PriceBar, ...] = ()
    dividends: tuple[Dividend, ...] = ()
    splits: tuple[Split, ...] = ()
