"""Return calculations. Inputs are date-indexed float prices (see adapters)"""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def simple_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Period-over-period simple returns. The first row (no prior price) is dropped.
    """
    return prices.pct_change(fill_method=None).iloc[1:]


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Period-over-period log returns. The first row is dropped."""
    ratio = prices / prices.shift(1)
    return cast(pd.DataFrame, np.log(ratio)).iloc[1:]


def annualized_return(
    returns: pd.Series[float],
    *,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Geometric (compond) annualized return from simple returns."""
    n = len(returns)
    if n == 0:
        return float("nan")
    growth = cast(float, (1.0 + returns).prod())
    return float(growth ** (periods_per_year / n)) - 1.0


def mean_annual_returns(
    returns: pd.DataFrame,
    *,
    periods_per_year: int = TRADING_DAYS,
) -> pd.Series[float]:
    """Arithmetic annualized mean return per column (mean * periods)

    Used as expected returns for mean-variance. Arithmetic, not geometric,
    because the mean-variance objective is defined on expected single-period
    returns. It overstates compound growth by roughly variance / 2.
    """
    return returns.mean() * periods_per_year
