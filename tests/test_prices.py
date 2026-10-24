from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from quant_dashboard.marketdata.repository import AmbiguousSecurityError, UnknownSecurityError
from quant_dashboard.marketdata.sql import SqlPriceRepository
from quant_dashboard.models import (
    CorporateAction,
    CorporateActionKind,
    DailyPrice,
    IngestionRun,
    Security,
)

# 10 consecutive calendar days.
DAYS = [date(2024, 1, 1) + timedelta(days=i) for i in range(10)]


def seed(
    session: Session,
    ticker: str,
    close: str = "100",
    dividends: Sequence[tuple[date, str]] = (),
) -> None:
    """Insert a security with a flat price series and the given dividends"""
    run = IngestionRun(source="test")
    security = Security(ticker=ticker, mic="XNAS", currency="USD")
    session.add_all([run, security])
    session.flush()

    price = Decimal(close)
    session.add_all(
        DailyPrice(
            security_id=security.id,
            trade_date=d,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=1_000,
            adj_close=price,
            ingestion_run_id=run.id,
        )
        for d in DAYS
    )
    session.add_all(
        CorporateAction(
            security_id=security.id,
            kind=CorporateActionKind.DIVIDEND,
            ex_date=ex_date,
            cash_amount=Decimal(amount),
            currency="USD",
            ingestion_run_id=run.id,
        )
        for ex_date, amount in dividends
    )
    session.commit()


def test_dividends_compound_into_adjusted_close(session: Session) -> None:
    seed(
        session,
        "AAA",
        dividends=[
            (DAYS[0], "5"),  # on the first bar: no prior close, so it cannot be applied
            (DAYS[3], "2"),
            (DAYS[5], "2"),
        ],
    )

    bars = SqlPriceRepository(session).get_prices("AAA")

    # Each $2 dividend on a flat $100 stock scales earlier bars by 0.98
    assert [b.adj_close for b in bars] == (
        [Decimal("96.04")] * 3 + [Decimal("98")] * 2 + [Decimal("100")] * 5
    )
    assert all(b.close == Decimal(100) for b in bars)  # raw prices are untouched
    assert bars[-1].adj_factor == Decimal(1)  # anchored at the latest bar


def test_window_is_inclusive_and_does_not_change_adjusted_values(session: Session) -> None:
    seed(session, "AAA", dividends=[(DAYS[5], "2")])
    repo = SqlPriceRepository(session)

    full = repo.get_prices("AAA")
    early = repo.get_prices("AAA", start=DAYS[2], end=DAYS[4])
    late = repo.get_prices("AAA", start=DAYS[6])

    # A window that ends before the dividend still reflect it, and is just a slice
    assert [b.trade_date for b in early] == DAYS[2:5]
    assert early == full[2:5]
    assert early[0].adj_close == Decimal("98")
    assert late == full[6:]
    assert all(b.adj_factor == Decimal(1) for b in late)


def test_dividend_larger_than_price_is_rejected(session: Session) -> None:
    seed(session, "AAA", dividends=[(DAYS[5], "150")])

    with pytest.raises(ValueError, match="dividend"):
        SqlPriceRepository(session).get_prices("AAA")


def test_unkown_and_ambiguous_tickers_raise(session: Session) -> None:
    session.add_all(
        [
            Security(ticker="AAA", mic="XNAS", currency="USD"),
            Security(ticker="AAA", mic="XNYS", currency="USD"),
        ]
    )
    session.commit()
    repo = SqlPriceRepository(session)

    with pytest.raises(UnknownSecurityError):
        repo.get_prices("ZZZ")
    with pytest.raises(AmbiguousSecurityError):
        repo.get_prices("AAA")
    assert repo.get_prices("AAA", mic="XNYS") == []  # disambiguated; no prices stored


def test_get_prices_many_returns_each_ticker_over_the_window(session: Session) -> None:
    seed(session, "AAA")
    seed(session, "BBB", close="50")

    result = SqlPriceRepository(session).get_prices_many(["AAA", "BBB"], start=DAYS[8])

    assert set(result) == {"AAA", "BBB"}
    assert [b.trade_date for b in result["AAA"]] == DAYS[8:]
    assert result["BBB"][0].close == Decimal(50)
