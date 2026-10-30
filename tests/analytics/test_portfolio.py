from __future__ import annotations

import pandas as pd
import pytest

from quant_dashboard.analytics.portfolio import rebalance_trades
from quant_dashboard.analytics.risk import max_drawdown

HOLDINGS = {"AAA": 10.0, "BBB": 5.0, "ZZZ": 20.0}  # ZZZ is not in the targets
PRICES = pd.Series({"AAA": 100.0, "BBB": 50.0, "CCC": 25.0, "ZZZ": 10.0})
TARGET = pd.Series({"AAA": 0.5, "BBB": 0.3, "CCC": 0.2})


def test_rebalance_reaches_target_weights_and_exits_dropped_holdings() -> None:
    plan = rebalance_trades(HOLDINGS, PRICES, TARGET, cash=100.0)

    values = plan.trades["target_shares"] * plan.trades["price"]
    weights = values.reindex(TARGET.index) / values.sum()
    pd.testing.assert_series_equal(weights, TARGET, check_names=False)
    assert plan.trades.loc["ZZZ", "target_shares"] == 0.0
    assert plan.cash_after == pytest.approx(0.0, abs=1e-9)


def test_rebalance_whole_shares_never_overspends() -> None:
    plan = rebalance_trades(HOLDINGS, PRICES, TARGET, cash=137.0, whole_shares=True)

    shares = plan.trades["target_shares"]
    assert (shares == shares.round()).all()
    assert plan.cash_after >= -1e-9


def test_max_drawdown_matches_hand_calculation() -> None:
    # Wealth 1.10 -> 0.88 -> 0.924: worst fall is 0.88 / 1.10 - 1 = -20%.
    assert max_drawdown(pd.Series([0.10, -0.20, 0.05])) == pytest.approx(-0.20)
    # A first-period loss counts against the starting wealth of 1.0.
    assert max_drawdown(pd.Series([-0.10, 0.05])) == pytest.approx(-0.10)
