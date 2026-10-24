from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

ONE = Decimal(1)


def dividend_factors(
    closes: Sequence[tuple[date, Decimal]],
    dividends: Sequence[tuple[date, Decimal]],
) -> list[Decimal]:
    """
    Total-return adjustment factor for each bar.

    'closes' must be ascending by date and already split-adjusted; 'dividends'
    are (ex_date, cash amount) on the same share basis. For a dividend D with
    ex-date E, every bar before E is scaled by 1 - D / (close on the bar before E).
    The latest bar always has factor 1.
    """
    n = len(closes)
    dates = [d for d, _ in closes]

    # step[i] is the combined factor for dividends whose first bar on/after the
    # ex-date is bar i; it applies to bars 0...i-1
    step = [ONE] * (n + 1)
    for ex_date, amount in dividends:
        i = bisect_left(dates, ex_date)
        if i == 0 or i == n:
            continue  # no bar before the ex-date, or no bar on/after it
        prior_close = closes[i - 1][1]
        if amount >= prior_close:
            raise ValueError(f"dividend {amount} >= prior close {prior_close} on {ex_date}")
        step[i] *= ONE - amount / prior_close

    factors = [ONE] * n
    running = ONE
    for j in range(n - 1, -1, -1):
        running *= step[j + 1]
        factors[j] = running
    return factors
