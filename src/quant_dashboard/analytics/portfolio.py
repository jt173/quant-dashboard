"""Portfolio primitives: weights, portfolio returns, rebalancing trades"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd


def equal_weights(tickers: Sequence[str]) -> pd.Series[float]:
    if not tickers:
        raise ValueError("Need at least one ticker")
    return pd.Series(1.0 / len(tickers), index=list(tickers), dtype="float64")


def normalize_weights(weights: pd.Series[float]) -> pd.Series[float]:
    """Scale weights so they sum to 1. Raises if the total is zero or NaN"""
    total = weights.sum()
    if not np.isfinite(total) or total == 0.0:
        raise ValueError(f"Cannot normalize weights with sum {total}")
    return weights / total


def check_weights(weights: pd.Series[float], *, tol: float = 1e-8) -> None:
    """Raise ValueError unless weights are finite and sum to 1 within tolerance"""
    if weights.empty:
        raise ValueError("Weights are empty")
    if not np.isfinite(weights.to_numpy(dtype="float64")).all():
        raise ValueError("Weights contain NaN or infinite values")
    total = weights.sum()
    if abs(total - 1.0) > tol:
        raise ValueError(f"Weights must sum to 1, got {total}")


def portfolio_returns(
    returns: pd.DataFrame,
    weights: pd.Series[float],
) -> pd.Series[float]:
    """Return series of a constant-weight porfolio.

    Equivalent to rebalancing back to 'weights' at the start of every period.
    Dates where any weighted asset has a NaN return produce NaN
    """
    check_weights(weights)
    missing = [t for t in weights.index if t not in returns.columns]
    if missing:
        raise ValueError(f"No returns for: {', '.join(map(str, missing))}")
    aligned = returns[list(weights.index)]
    values = aligned.to_numpy(dtype="float64") @ weights.to_numpy(dtype="float64")
    return pd.Series(values, index=aligned.index, name="portfolio")


@dataclass(frozen=True)
class RebalancePlan:
    """Trades needed to reach target weights.

    trades columns: price, current_shares, target_shares, trade_shares,
    trade_value. Positive trade_shares are buys, negative are sells
    """

    trades: pd.DataFrame
    cash_after: float


def rebalance_trades(
    holdings: Mapping[str, float],
    prices: pd.Series[float],
    target_weights: pd.Series[float],
    *,
    cash: float = 0.0,
    whole_shares: bool = False,
) -> RebalancePlan:
    """Compute trades that move a portfolio to 'target_weights'.

    Total value is holdings at 'prices' plus 'cash'; each target position is
    weight * total value. Holdings absent from the targets are sold in full.

    whole_shares:
        Target share counts are floored, so the plan never spends more than
        the available value and cash_after is always >= 0. Fractional shares
        (the default) hit the targets exactly.

    Long-only: negative target weights raise ValueError.
    """
    check_weights(target_weights)
    if (target_weights < 0).any():
        raise ValueError("Short positions are not supported")

    universe = list(target_weights.index) + [t for t in holdings if t not in target_weights.index]
    px = prices.reindex(universe)
    bad = px[px.isna() | (px <= 0)]
    if not bad.empty:
        raise ValueError(f"Missing or non-positive price for: {', '.join(bad.index)}")

    current = pd.Series(holdings, dtype="float64").reindex(universe, fill_value=0.0)
    target = target_weights.reindex(universe, fill_value=0.0)

    total_value = (current * px).sum() + cash
    if total_value <= 0.0:
        raise ValueError("Portfolio value must be positive")

    target_shares = target * total_value / px
    if whole_shares:
        target_shares = cast(pd.Series, np.floor(target_shares))

    trade_shares = target_shares - current
    trade_value = trade_shares * px
    trades = pd.DataFrame(
        {
            "price": px,
            "current_shares": current,
            "target_shares": target_shares,
            "trade_shares": trade_shares,
            "trade_value": trade_value,
        }
    )
    return RebalancePlan(trades=trades, cash_after=cash - trade_value.sum())
