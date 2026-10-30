"""Run the Phase 2 optimizers on a universe from the database.

Usage:
    make optimize ARGS="AAPL MSFT XOM JPM --start 2019-01-01 --max-weight 0.4"

Results are in-sample: the optimizers and the metrics see the same data.
Out-of-sample evaluation is being implemented in Phase 3.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections.abc import Mapping, Sequence

import pandas as pd

from quant_dashboard.analytics.adapters import PriceBar, bars_to_frame
from quant_dashboard.analytics.constraints import Constraints
from quant_dashboard.analytics.optimizers import max_sharpe, min_variance, risk_parity
from quant_dashboard.analytics.portfolio import equal_weights, portfolio_returns
from quant_dashboard.analytics.returns import (
    annualized_return,
    mean_annual_returns,
    simple_returns,
)
from quant_dashboard.analytics.risk import (
    annualized_volatility,
    covariance_matrix,
    max_drawdown,
    sharpe_ratio,
)
from quant_dashboard.db import SessionLocal
from quant_dashboard.marketdata.sql import SqlPriceRepository


def load_bars(
    tickers: Sequence[str],
    start: dt.date | None,
    end: dt.date | None,
) -> Mapping[str, Sequence[PriceBar]]:
    with SessionLocal() as session:
        return SqlPriceRepository(session).get_prices_many(tickers, start=start, end=end)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("--max-weight", type=float, default=None)
    parser.add_argument("--risk-free", type=float, default=0.0, help="annual rate")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    prices = bars_to_frame(load_bars(args.tickers, args.start, args.end))
    returns = simple_returns(prices)
    cov = covariance_matrix(returns)
    mu = mean_annual_returns(returns)
    constraints = Constraints(long_only=True, max_weight=args.max_weight)
    rf: float = args.risk_free

    portfolios = {
        "min_variance": min_variance(cov, constraints).weights,
        "max_sharpe": max_sharpe(cov, mu, risk_free_rate=rf, constraints=constraints).weights,
        "risk_parity": risk_parity(cov, constraints=constraints).weights,
        "equal_weight": equal_weights([str(c) for c in prices.columns]),
    }

    metrics = {}
    for name, weights in portfolios.items():
        r = portfolio_returns(returns, weights)
        metrics[name] = {
            "ann_return": annualized_return(r),
            "ann_vol": annualized_volatility(r),
            "sharpe": sharpe_ratio(r, risk_free_rate=rf),
            "max_drawdown": max_drawdown(r),
        }

    print(
        f"{len(returns)} daily returns, {returns.index[0].date()} to {returns.index[-1].date()}\n"
    )
    print("Weights")
    print(pd.DataFrame(portfolios).round(4).to_string())
    print("\nIn-sample metrics")
    print(pd.DataFrame(metrics).round(4).to_string())


if __name__ == "__main__":
    main()
