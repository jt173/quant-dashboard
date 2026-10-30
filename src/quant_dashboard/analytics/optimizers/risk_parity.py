from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from quant_dashboard.analytics.constraints import DEFAULT_CONSTRAINTS, Constraints
from quant_dashboard.analytics.optimizers.base import (
    Floats,
    OptimizationError,
    OptimizationResult,
    build_result,
    prepare_covariance,
)


def risk_parity(
    cov: pd.DataFrame,
    *,
    risk_budgets: pd.Series[float] | None = None,
    constraints: Constraints = DEFAULT_CONSTRAINTS,
) -> OptimizationResult:
    """Weights whose risk contributions match `risk_budgets` (default: equal).

    Minimizes sum_i (RC_i - b_i)^2, where RC_i = w_i (Sigma w)_i / (w'Sigma w)
    is asset i's share of portfolio variance. With a binding max_weight,
    exact parity may be impossible; the result is then the closest feasible fit.
    """
    if not constraints.long_only:
        raise ValueError("Risk parity requires long_only=True")

    tickers, sigma = prepare_covariance(cov)
    n = len(tickers)
    _, upper = constraints.bounds(n)

    if risk_budgets is None:
        budgets: Floats = np.full(n, 1.0 / n)
    else:
        aligned = risk_budgets.reindex(tickers)
        if aligned.isna().any() or (aligned <= 0).any():
            raise ValueError("risk_budgets must be positive for every ticker")
        budgets = np.asarray(aligned, dtype="float64")
        if abs(budgets.sum() - 1.0) > 1e-8:
            raise ValueError("risk_budgets must sum to 1")

    def objective(w: Floats) -> float:
        marginal = sigma @ w
        total = float(w @ marginal)
        return float(np.sum((w * marginal / total - budgets) ** 2))

    inverse_vol = 1.0 / np.sqrt(np.diag(sigma))
    x0 = inverse_vol / inverse_vol.sum()

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=[(0.0, 1.0 if upper is None else upper)] * n,
        constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}],
        options={"ftol": 1e-14, "maxiter": 1000},
    )
    if not result.success:
        raise OptimizationError(f"SLSQP failed: {result.message}")
    return build_result(result.x, tickers, sigma, None, "scipy-slsqp")
