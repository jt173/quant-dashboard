from __future__ import annotations

from typing import Any

import cvxpy as cp
import pandas as pd

from quant_dashboard.analytics.constraints import DEFAULT_CONSTRAINTS, Constraints
from quant_dashboard.analytics.optimizers.base import (
    OptimizationError,
    OptimizationResult,
    build_result,
    prepare_covariance,
    prepare_expected_returns,
    solved_values,
)


def mean_variance(
    cov: pd.DataFrame,
    expected_returns: pd.Series[float],
    *,
    risk_aversion: float | None = None,
    target_return: float | None = None,
    constraints: Constraints = DEFAULT_CONSTRAINTS,
) -> OptimizationResult:
    """Markowitz mean-variance optimization. Inputs are annualized.

    Give exactly one of:
        risk_aversion: maximize mu'w - (risk_aversion / 2) * w'Sigma w
        target_return: minimize variance subject to mu'w >= target_return
    """
    if (risk_aversion is None) == (target_return is None):
        raise ValueError("Provide exactly one of risk_aversion or target_return")
    if risk_aversion is not None and risk_aversion <= 0:
        raise ValueError("risk_aversion must be positive")

    tickers, sigma = prepare_covariance(cov)
    mu = prepare_expected_returns(expected_returns, tickers)
    n = len(tickers)
    lower, upper = constraints.bounds(n)

    w = cp.Variable(n)
    variance = cp.quad_form(w, cp.psd_wrap(sigma))
    rules: list[Any] = [cp.sum(w) == 1]
    if lower is not None:
        rules.append(w >= lower)
    if upper is not None:
        rules.append(w <= upper)

    if risk_aversion is not None:
        objective = cp.Maximize(mu @ w - (risk_aversion / 2.0) * variance)
    else:
        rules.append(mu @ w >= target_return)
        objective = cp.Minimize(variance)

    problem = cp.Problem(objective, rules)
    problem.solve()
    return build_result(solved_values(problem, w), tickers, sigma, mu, "cvxpy")


def max_sharpe(
    cov: pd.DataFrame,
    expected_returns: pd.Series[float],
    *,
    risk_free_rate: float,
    constraints: Constraints = DEFAULT_CONSTRAINTS,
) -> OptimizationResult:
    """Maximum Sharpe (tangency) portfolio. Inputs and risk_free_rate are annual

    The Sharpe ratio is not convex in w, so this uses the standard
    homogenizing subsitution y = kappa * w: minimize y'Sigma y subject to
    (mu - rf)'y = 1 and sum(y) = kappa >= 0, then recover w = y / kappa.
    """
    tickers, sigma = prepare_covariance(cov)
    mu = prepare_expected_returns(expected_returns, tickers)
    excess = mu - risk_free_rate
    if not (excess > 0).any():
        raise OptimizationError("No asset has an expected return above the risk-free rate.")
    n = len(tickers)
    lower, upper = constraints.bounds(n)

    y = cp.Variable(n)
    kappa = cp.Variable(nonneg=True)
    rules = [excess @ y == 1, cp.sum(y) == kappa]
    if lower is not None:
        rules.append(y >= lower * kappa)
    if upper is not None:
        rules.append(y <= upper * kappa)

    problem = cp.Problem(cp.Minimize(cp.quad_form(y, cp.psd_wrap(sigma))), rules)
    problem.solve()
    y_val = solved_values(problem, y)
    kappa_val = float(solved_values(problem, kappa))
    if kappa_val < 1e-9:
        raise OptimizationError("Degenerate solution (kappa ~ 0)")
    return build_result(y_val / kappa_val, tickers, sigma, mu, "cvxpy")
