"""Boundary between the data layer (Decimal) and the analytics (float, pandas)"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Literal, Protocol

import pandas as pd


class PriceBar(Protocol):
    """Structural view of a price bar. marketdata's AdjustedBar satisfies it."""

    @property
    def trade_date(self) -> dt.date: ...

    @property
    def adj_close(self) -> Decimal: ...


def bars_to_frame(
    bars: Mapping[str, Sequence[PriceBar]],
    *,
    missing: Literal["drop", "keep"] = "drop",
) -> pd.DataFrame:
    """
    Convert per-ticker adjusted bars into a float DataFrame.

    Index: DatetimeIndex named "date", sorted ascending.
    Columns: tickers (named "ticker"), in the mappings order.

    missing:
        "drop" removes any date where at least one ticker has no price,
        so every row is a fully observed cross-section. "keep" leaves NaNs
        in place. Values are never forward filled: that would fabricate zero
        returns on days a security did not trade.

    Raises:
        ValueError: if any requested ticker has no bars at all. An empty
        column would otherwise make "drop" silently return an empty frame.
    """
    empty = [ticker for ticker, rows in bars.items() if not rows]
    if empty:
        raise ValueError(f"No price data for: {', '.join(sorted(empty))}")

    series = {
        ticker: pd.Series(
            {pd.Timestamp(b.trade_date): float(b.adj_close) for b in rows},
            dtype="float64",
        )
        for ticker, rows in bars.items()
    }
    frame = pd.DataFrame(series).sort_index()
    if missing == "drop":
        frame = frame.dropna(how="any")
    frame.index.name = "date"
    frame.columns.name = "ticker"
    return frame
