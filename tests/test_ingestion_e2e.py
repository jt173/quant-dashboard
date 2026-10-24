from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from quant_dashboard.ingestion.service import (
    SecuritySpec,
    ensure_securities,
    execute_run,
    plan_run,
)
from quant_dashboard.ingestion.source import SourceError
from quant_dashboard.ingestion.types import DailyData, Dividend, PriceBar, Split
from quant_dashboard.models import (
    CorporateAction,
    CorporateActionKind,
    DailyPrice,
    DataQualityIssue,
    IngestionRunItem,
    ItemStatus,
    RunStatus,
    Security,
    Severity,
)

START = date(2024, 1, 1)  # a Monday


# --- helpers ---
def weekdays(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def bar(d: date, price: str) -> PriceBar:
    p = Decimal(price)
    return PriceBar(d, p, p, p, p, p, 1_000)


def series(start: date, n: int, price: str) -> tuple[PriceBar, ...]:
    return tuple(bar(d, price) for d in weekdays(start, n))


class FakeSource:
    """Serves canned data, honoring the [start, end) window like a real provider."""

    name = "fake"

    def __init__(self, data: dict[str, DailyData]) -> None:
        self.data = data
        self.failing: set[str] = set()
        self.calls: list[tuple[str, date]] = []

    def fetch_daily(self, symbol: str, start: date, end: date | None = None) -> DailyData:
        self.calls.append((symbol, start))
        if symbol in self.failing:
            raise SourceError("simulated outage")
        full = self.data[symbol]

        def in_window(d: date) -> bool:
            return d >= start and (end is None or d < end)

        return DailyData(
            symbol=symbol,
            bars=tuple(b for b in full.bars if in_window(b.trade_date)),
            dividends=tuple(x for x in full.dividends if in_window(x.ex_date)),
            splits=tuple(x for x in full.splits if in_window(x.ex_date)),
        )


def run_ingest(
    session: Session, source: FakeSource, tickers: list[str], end: date
) -> tuple[int, RunStatus]:
    specs = [SecuritySpec(ticker=t, mic="XNAS", currency="USD") for t in tickers]
    securities = ensure_securities(session, specs)
    run_id = plan_run(
        session,
        source_name=source.name,
        securities=securities,
        default_start=START,
        end=end,
    )
    return run_id, execute_run(session, source, run_id)


def price_rows(session: Session) -> list[tuple[object, ...]]:
    rows = session.execute(
        select(
            DailyPrice.security_id, DailyPrice.trade_date, DailyPrice.close, DailyPrice.volume
        ).order_by(DailyPrice.security_id, DailyPrice.trade_date)
    ).all()
    return [tuple(r) for r in rows]


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


# --- behaviors ---


def test_rerunning_ingestion_is_idempotent(session: Session) -> None:
    days = weekdays(START, 20)
    source = FakeSource(
        {
            "AAA": DailyData(
                "AAA",
                bars=series(START, 20, "100"),
                dividends=(Dividend(days[10], Decimal("0.5")),),
            )
        }
    )

    _, first = run_ingest(session, source, ["AAA"], days[-1])
    print(session.execute(select(IngestionRunItem.status, IngestionRunItem.error)).all())
    print(session.execute(select(DataQualityIssue.check_name, DataQualityIssue.message)).all())
    rows_after_first = price_rows(session)
    _, second = run_ingest(session, source, ["AAA"], days[-1])

    assert first == second == RunStatus.SUCCEEDED
    assert len(rows_after_first) == 20
    assert price_rows(session) == rows_after_first
    assert count(session, CorporateAction) == 1


def test_bad_bars_are_quarantined_without_blocking_other_tickers(session: Session) -> None:
    days = weekdays(START, 10)
    bad_bars = list(series(START, 10, "100"))
    # high (90) is below open (100): violates OHLC consistency
    bad_bars[4] = PriceBar(
        days[4], Decimal("100"), Decimal("90"), Decimal("80"), Decimal("85"), Decimal("85"), 1_000
    )
    source = FakeSource(
        {
            "GOOD": DailyData("GOOD", bars=series(START, 10, "50")),
            "BAD": DailyData("BAD", bars=tuple(bad_bars)),
        }
    )

    run_id, status = run_ingest(session, source, ["GOOD", "BAD"], days[-1])

    assert status == RunStatus.PARTIAL
    bars_per_ticker = dict(
        session.execute(
            select(Security.ticker, func.count(DailyPrice.trade_date))
            .outerjoin(DailyPrice, DailyPrice.security_id == Security.id)
            .group_by(Security.ticker)
        ).all()
    )
    assert bars_per_ticker == {"GOOD": 10, "BAD": 0}

    bad_item = session.scalars(
        select(IngestionRunItem)
        .join(Security, Security.id == IngestionRunItem.security_id)
        .where(Security.ticker == "BAD")
    ).one()
    assert bad_item.status == ItemStatus.QUARANTINED

    issue = session.scalars(select(DataQualityIssue).where(DataQualityIssue.run_id == run_id)).one()
    assert (issue.check_name, issue.severity, issue.trade_date) == (
        "ohlc_inconsistent",
        Severity.ERROR,
        days[4],
    )


def test_new_split_restates_stored_history(session: Session) -> None:
    days = weekdays(START, 30)
    source = FakeSource({"AAA": DailyData("AAA", bars=series(START, 20, "100"))})
    run_ingest(session, source, ["AAA"], days[19])

    # The provider now reports a 2-for-1 split and restates the entire history.
    source.data["AAA"] = DailyData(
        "AAA",
        bars=series(START, 30, "50"),
        splits=(Split(days[25], Decimal("2")),),
    )
    _, status = run_ingest(session, source, ["AAA"], days[29])

    assert status == RunStatus.SUCCEEDED
    assert count(session, DailyPrice) == 30
    # The oldest bar lies outside the incremental window; it only changes if the
    # split triggered a full-history refresh.
    oldest_close = session.scalar(select(DailyPrice.close).order_by(DailyPrice.trade_date).limit(1))
    assert oldest_close == Decimal("50")

    split = session.scalars(select(CorporateAction)).one()
    assert (split.kind, split.split_from, split.split_to, split.ex_date) == (
        CorporateActionKind.SPLIT,
        Decimal(1),
        Decimal(2),
        days[25],
    )


def test_resume_retries_only_failed_items(session: Session) -> None:
    days = weekdays(START, 10)
    source = FakeSource({t: DailyData(t, bars=series(START, 10, "10")) for t in ("AAA", "BBB")})
    source.failing.add("BBB")

    run_id, first = run_ingest(session, source, ["AAA", "BBB"], days[-1])
    assert first == RunStatus.PARTIAL

    source.failing.clear()
    assert execute_run(session, source, run_id) == RunStatus.SUCCEEDED

    fetched = [symbol for symbol, _ in source.calls]
    assert fetched.count("AAA") == 1  # succeeded the first time, not retried
    assert fetched.count("BBB") == 2  # failed, then retried on resume
    assert count(session, DailyPrice) == 20
