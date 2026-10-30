"""Shared result type and input handling for optimizers"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

Floats = NDArray[np.float64]


class OptimizationError(RuntimeError):
    """The solver failed or the problem is infeasable."""


@dataclass(frozen=True)
class OptimizationResult:
    """weights: indexed by ticker, sums to 1.
    volatility / expected_return: annualized, in the units of the inputs.
    expected_return is None for optimizers that take no return estimates.
    """

    weights: pd.Series[float]
    volatility: float
    expected_return: float | None
    solver: str


def prepare_covariance(cov: pd.DataFrame) -> tuple[list[str], Floats]:
    if cov.shape[0] != cov.shape[1] or not cov.index.equals(cov.columns):
        raise ValueError("Covariance must be square with matching index and columns")
    mat = cov.to_numpy(dtype="float64")
    if not np.isfinite(mat).all():
        raise ValueError("Covariance containts NaN or infinite values")
    return [str(t) for t in cov.index], (mat + mat.T) / 2


def prepare_expected_returns(mu: pd.Series[float], tickers: list[str]) -> Floats:
    aligned = mu.reindex(tickers)
    if aligned.isna().any():
        missing = [t for t, v in aligned.items() if pd.isna(v)]
        raise ValueError(f"Missing expected returns for: {', '.join(map(str, missing))}")
    return np.asarray(aligned, dtype="float64")


def solved_values(problem: Any, variable: Any) -> Floats:
    """Return the optimal value of `variable`, or raise if the solve failed."""
    if problem.status != "optimal" or variable.value is None:
        raise OptimizationError(f"Solver finished with status '{problem.status}'")
    return np.asarray(variable.value, dtype=np.float64)


def build_result(
    raw_weights: Floats,
    tickers: list[str],
    cov: Floats,
    mu: Floats | None,
    solver: str,
) -> OptimizationResult:
    # Strip solver noise (e.g. -1e-12 on a long-only problem), then renormalize
    w = np.where(np.abs(raw_weights) < 1e-10, 0.0, raw_weights)
    w = w / w.sum()
    return OptimizationResult(
        weights=pd.Series(w, index=tickers, dtype="float64"),
        volatility=float(np.sqrt(w @ cov @ w)),
        expected_return=None if mu is None else float(mu @ w),
        solver=solver,
    )
