from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp
from pypfopt import EfficientFrontier

from quant_dashboard.analytics.constraints import Constraints
from quant_dashboard.analytics.optimizers import (
    max_sharpe,
    mean_variance,
    min_variance,
    risk_parity,
)
from quant_dashboard.analytics.returns import mean_annual_returns
from quant_dashboard.analytics.risk import covariance_matrix, risk_contributions

RF = 0.02


@pytest.fixture
def returns() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    vol = np.array([0.010, 0.015, 0.008, 0.020, 0.012])
    mean = np.array([0.0004, 0.0006, 0.0003, 0.0008, 0.0005])
    corr = 0.3 * np.ones((5, 5)) + 0.7 * np.eye(5)
    data = rng.multivariate_normal(mean, corr * np.outer(vol, vol), size=750)
    index = pd.bdate_range("2021-01-04", periods=750)
    return pd.DataFrame(data, columns=tickers, index=index)


@pytest.mark.parametrize(
    ("max_weight", "bounds"),
    [(None, (0.0, 1.0)), (0.4, (0.0, 0.4))],
)
def test_optimizers_match_pyportfolioopt(
    returns: pd.DataFrame,
    max_weight: float | None,
    bounds: tuple[float, float],
) -> None:
    cov = covariance_matrix(returns)
    mu = mean_annual_returns(returns)
    constraints = Constraints(max_weight=max_weight)

    def reference(method: str, **kwargs: float) -> np.ndarray:
        frontier = EfficientFrontier(mu, cov, weight_bounds=bounds)
        weights = pd.Series(getattr(frontier, method)(**kwargs))
        return weights.reindex(cov.index).to_numpy(dtype="float64")

    cases = {
        "min_variance": (
            min_variance(cov, constraints).weights,
            reference("min_volatility"),
        ),
        "max_sharpe": (
            max_sharpe(cov, mu, risk_free_rate=RF, constraints=constraints).weights,
            reference("max_sharpe", risk_free_rate=RF),
        ),
        "mean_variance": (
            mean_variance(cov, mu, risk_aversion=2.0, constraints=constraints).weights,
            reference("max_quadratic_utility", risk_aversion=2.0),
        ),
    }
    for name, (ours, theirs) in cases.items():
        np.testing.assert_allclose(ours.to_numpy(), theirs, atol=1e-3, err_msg=name)


def test_risk_parity_equalizes_risk_contributions(returns: pd.DataFrame) -> None:
    cov = covariance_matrix(returns)

    equal = risk_parity(cov).weights
    np.testing.assert_allclose(risk_contributions(equal, cov).to_numpy(), 0.2, atol=1e-4)

    budgets = pd.Series([0.4, 0.2, 0.2, 0.1, 0.1], index=cov.index)
    weighted = risk_parity(cov, risk_budgets=budgets).weights
    np.testing.assert_allclose(
        risk_contributions(weighted, cov).to_numpy(), budgets.to_numpy(), atol=1e-4
    )


@st.composite
def covariances(draw: st.DrawFn) -> pd.DataFrame:
    n = draw(st.integers(min_value=3, max_value=6))
    a = draw(hnp.arrays(np.float64, (n, n), elements=st.floats(-1.0, 1.0)))
    names = [f"T{i}" for i in range(n)]
    return pd.DataFrame(a @ a.T + 0.01 * np.eye(n), index=names, columns=names)


@given(
    cov=covariances(),
    max_weight=st.sampled_from([None, 0.5, 1.0]),
    mu_seed=st.integers(min_value=0, max_value=1000),
)
@settings(max_examples=50, deadline=None)
def test_weights_respect_constraints_and_min_variance_is_optimal(
    cov: pd.DataFrame,
    max_weight: float | None,
    mu_seed: int,
) -> None:
    constraints = Constraints(max_weight=max_weight)
    mu = pd.Series(np.random.default_rng(mu_seed).uniform(-0.1, 0.3, len(cov)), index=cov.index)
    cap = 1.0 if max_weight is None else max_weight

    results = {
        "min_variance": min_variance(cov, constraints),
        "mean_variance": mean_variance(cov, mu, risk_aversion=3.0, constraints=constraints),
        "risk_parity": risk_parity(cov, constraints=constraints),
    }
    for name, result in results.items():
        w = result.weights.to_numpy()
        assert w.sum() == pytest.approx(1.0, abs=1e-6), name
        assert w.min() >= -1e-4, name
        assert w.max() <= cap + 1e-4, name

    equal = np.full(len(cov), 1.0 / len(cov))
    equal_vol = float(np.sqrt(equal @ cov.to_numpy() @ equal))
    assert results["min_variance"].volatility <= equal_vol + 1e-3
