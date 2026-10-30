from __future__ import annotations

from typing import Any

import cvxpy as cp
import pandas as pd

from quant_dashboard.analytics.constraints import DEFAULT_CONSTRAINTS, Constraints
from quant_dashboard.analytics.optimizers.base import (
    OptimizationResult,
    build_result,
    prepare_covariance,
    solved_values,
)


def min_variance(
    cov: pd.DataFrame,
    constraints: Constraints = DEFAULT_CONSTRAINTS,
) -> OptimizationResult:
    """Global minimum-variance portfolio. `cov` should be annualized."""
    tickers, sigma = prepare_covariance(cov)
    n = len(tickers)
    lower, upper = constraints.bounds(n)

    w = cp.Variable(n)
    rules: list[Any] = [cp.sum(w) == 1]
    if lower is not None:
        rules.append(w >= lower)
    if upper is not None:
        rules.append(w <= upper)

    problem = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), rules)
    problem.solve()
    return build_result(solved_values(problem, w), tickers, sigma, None, "cvxpy")
