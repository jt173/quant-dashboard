from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from quant_dashboard.models import Severity

from .types import DailyData, PriceBar


@dataclass(frozen=True, slots=True)
class QualityIssue:
    severity: Severity
    code: str
    trade_date: date | None
    message: str


def check_daily_data(
    data: DailyData,
    *,
    max_gap_days: int = 5,
    max_daily_move: Decimal = Decimal("0.4"),
    adj_jump_tolerance: Decimal = Decimal("0.001"),
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    issues += _duplicates(data.bars)
    bars = sorted(data.bars, key=lambda b: b.trade_date)
    issues += _bar_sanity(bars)
    issues += _gaps(bars, max_gap_days)
    issues += _extreme_moves(bars, max_daily_move)
    issues += _adjustment_jumps(bars, {d.ex_date for d in data.dividends}, adj_jump_tolerance)
    return issues


def _duplicates(bars: tuple[PriceBar, ...]) -> list[QualityIssue]:
    counts = Counter(b.trade_date for b in bars)
    return [
        QualityIssue(Severity.ERROR, "duplicate_date", d, f"{n} bars for {d}")
        for d, n in counts.items()
        if n > 1
    ]


def _bar_sanity(bars: list[PriceBar]) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for b in bars:
        prices = (b.open, b.high, b.low, b.close, b.adj_close)
        if any(p <= 0 for p in prices):
            issues.append(
                QualityIssue(Severity.ERROR, "non_positive_price", b.trade_date, "price <= 0")
            )
        if b.volume < 0:
            issues.append(
                QualityIssue(Severity.ERROR, "negative_volume", b.trade_date, f"volume {b.volume}")
            )
        if b.high < max(b.open, b.close, b.low) or b.low > min(b.open, b.close, b.high):
            issues.append(
                QualityIssue(
                    Severity.ERROR,
                    "ohlc_inconsistent",
                    b.trade_date,
                    "high/low do not bound open/close",
                )
            )
    return issues


def _gaps(bars: list[PriceBar], max_gap_days: int) -> list[QualityIssue]:
    # 5 calendar days tolerates a long weekend; tune per exchange if needed.
    return [
        QualityIssue(
            Severity.WARNING,
            "gap",
            cur.trade_date,
            f"{(cur.trade_date - prev.trade_date).days} days since {prev.trade_date}",
        )
        for prev, cur in pairwise(bars)
        if (cur.trade_date - prev.trade_date).days > max_gap_days
    ]


def _extreme_moves(bars: list[PriceBar], max_move: Decimal) -> list[QualityIssue]:
    # `close` is already split-adjusted, so a huge move is suspicious either way.
    issues: list[QualityIssue] = []
    for prev, cur in pairwise(bars):
        if prev.close > 0 and abs(cur.close / prev.close - 1) > max_move:
            issues.append(
                QualityIssue(
                    Severity.WARNING,
                    "extreme_move",
                    cur.trade_date,
                    f"close {prev.close} -> {cur.close}",
                )
            )
    return issues


def _adjustment_jumps(
    bars: list[PriceBar], dividend_dates: set[date], tol: Decimal
) -> list[QualityIssue]:
    # adj_close/close should only change on a dividend ex-date. A jump anywhere
    # else points to a bad adjustment (the classic split/dividend data bug).
    issues: list[QualityIssue] = []
    for prev, cur in pairwise(bars):
        if prev.close <= 0 or cur.close <= 0 or prev.adj_close <= 0:
            continue  # already reported as non_positive_price
        change = (cur.adj_close / cur.close) / (prev.adj_close / prev.close)
        if abs(change - 1) > tol and cur.trade_date not in dividend_dates:
            issues.append(
                QualityIssue(
                    Severity.WARNING,
                    "adjustment_jump",
                    cur.trade_date,
                    f"adj factor changed {change:.4f} with no dividend",
                )
            )
    return issues
