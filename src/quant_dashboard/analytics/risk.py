"""Risk and risk-adjusted performance metrics on simple return series."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_dashboard.analytics.returns import TRADING_DAYS


def _per_period_rate(annual_rate: float, periods_per_year: int) -> float:
    """Convert an annual rate to its compounding-equivalent per-period rate."""
    return float((1.0 + annual_rate) ** (1.0 / periods_per_year)) - 1.0


def annualized_volatility(
    returns: pd.Series[float],
    *,
    periods_per_year: int = TRADING_DAYS,
    ddof: int = 1,
) -> float:
    return float(returns.std(ddof=ddof) * np.sqrt(periods_per_year))


def drawdown_series(returns: pd.Series[float]) -> pd.Series[float]:
    """Drawdown from the running peak, as non-positive fractions.

    The peak starts at 1.0 (initial wealth), so a loss on the very first
    period registers as a drawdown.
    """
    wealth = (1.0 + returns).cumprod()
    peak = wealth.cummax().clip(lower=1.0)
    return wealth / peak - 1.0


def max_drawdown(returns: pd.Series[float]) -> float:
    """Worst drawdown as a non-positive fraction"""
    if len(returns) == 0:
        return float("nan")
    return float(drawdown_series(returns).min())


def sharpe_ratio(
    returns: pd.Series[float],
    *,
    risk_free_rate: float,
    periods_per_year: int = TRADING_DAYS,
    ddof: int = 1,
) -> float:
    """Annualized Sharpe ratio. risk_free_rate is an annual rate

    Returns NaN when excess returns have zero variance
    """
    excess = returns - _per_period_rate(risk_free_rate, periods_per_year)
    std = float(excess.std(ddof=ddof))
    if std == 0.0 or np.isnan(std):
        return float("nan")
    return float(excess.mean()) / std * float(np.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series[float],
    *,
    risk_free_rate: float,
    periods_per_year: int = TRADING_DAYS,
) -> float:
    """Annualized Sortino ration with the risk-free rate as the target return

    Downside deviation is sqrt(mean(min(excess, 0)^2)) over ALL periods, not
    only the losing ones.
    """
    excess = returns - _per_period_rate(risk_free_rate, periods_per_year)
    downside = float(np.sqrt((excess.clip(upper=0.0) ** 2).mean()))
    if downside == 0.0 or np.isnan(downside):
        return float("nan")
    return float(excess.mean()) / downside * float(np.sqrt(periods_per_year))


def covariance_matrix(
    returns: pd.DataFrame,
    *,
    annualize: bool = True,
    periods_per_year: int = TRADING_DAYS,
    ddof: int = 1,
) -> pd.DataFrame:
    cov = returns.cov(ddof=ddof)
    return cov * periods_per_year if annualize else cov


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.corr()


def risk_contributions(
    weights: pd.Series[float],
    cov: pd.DataFrame,
) -> pd.Series[float]:
    """Fraction of total portfolio variance contributed by each asset.

    Sums to 1. Equal values across assets means equal risk contribution.
    """
    w = weights.to_numpy(dtype="float64")
    sigma = cov.loc[weights.index, weights.index].to_numpy(dtype="float64")
    marginal = sigma @ w
    total = float(w @ marginal)
    return pd.Series(w * marginal / total, index=weights.index)
