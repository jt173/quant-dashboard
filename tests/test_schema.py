"""The database, not just the application, must refuse bad market data."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from quant_dashboard.models import (
    CorporateAction,
    CorporateActionKind,
    DailyPrice,
    DataQualityIssue,
    IngestionRun,
    IngestionRunItem,
    ItemStatus,
    RunStatus,
    Security,
    Severity,
)

D = Decimal
DAY = date(2024, 1, 1)


@contextmanager
def rejected(db: Session, constraint: str) -> Iterator[None]:
    """
    Expect Postgres to reject the statements inside, naming 'constraint' in its error.
    The failing statement runs in a SAVEPOINT so the test's transaction stays usable
    """
    with pytest.raises(IntegrityError, match=constraint), db.begin_nested():
        yield


@pytest.fixture
def security(db: Session) -> Security:
    sec = Security(ticker="AAPL", mic="XNAS", name="Apple Inc.", currency="USD")
    db.add(sec)
    db.flush()
    return sec


@pytest.fixture
def run(db: Session) -> IngestionRun:
    ingestion_run = IngestionRun(source="fixture")
    db.add(ingestion_run)
    db.flush()
    return ingestion_run


def make_bar(security: Security, run: IngestionRun, **overrides: Any) -> DailyPrice:
    values: dict[str, Any] = {
        "security_id": security.id,
        "trade_date": DAY,
        "open": D("10"),
        "high": D("11"),
        "low": D("9"),
        "close": D("10.5"),
        "volume": 1000,
        "ingestion_run_id": run.id,
    }
    return DailyPrice(**(values | overrides))


def make_action(security: Security, run: IngestionRun, **overrides: Any) -> CorporateAction:
    values: dict[str, Any] = {
        "security_id": security.id,
        "kind": CorporateActionKind.SPLIT,
        "ex_date": DAY,
        "split_from": D("1"),
        "split_to": D("4"),
        "ingestion_run_id": run.id,
    }
    return CorporateAction(**(values | overrides))


# --- Securities ---
def test_security_ticker_and_mic_are_unique_together(db: Session, security: Security) -> None:
    db.add(Security(ticker="AAPL", mic="XNYS", currency="USD"))
    db.flush()

    with rejected(db, "uq_securities_ticker_mic"):
        db.add(Security(ticker="AAPL", mic="XNAS", currency="USD"))
        db.flush()


def test_security_must_be_three_characters(db: Session) -> None:
    with rejected(db, "ck_securities_currency_iso_length"):
        db.add(Security(ticker="X", mic="XNAS", currency="US"))
        db.flush()


def test_security_cannot_delist_before_listing(db: Session) -> None:
    with rejected(db, "ck_securities_delisted_after_listed"):
        db.add(
            Security(
                ticker="X",
                mic="XNAS",
                currency="USD",
                listed_on=date(2020, 1, 1),
                delisted_on=date(2019, 1, 1),
            )
        )
        db.flush()


# --- Daily Prices ---


def test_valid_bar_round_trips_exact_decimals(
    db: Session, security: Security, run: IngestionRun
) -> None:
    db.add(make_bar(security, run, close=D("10.123456"), adj_close=D("5.061728")))
    db.flush()
    db.expire_all()

    bar = db.get(DailyPrice, (security.id, DAY))
    assert bar is not None
    assert bar.close == D("10.123456")
    assert bar.adj_close == D("5.061728")


def test_adj_close_is_optional(db: Session, security: Security, run: IngestionRun) -> None:
    db.add(make_bar(security, run, adj_close=None))
    db.flush()


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        pytest.param({"open": D("0"), "low": D("0")}, "prices_positive", id="zero-price"),
        pytest.param({"high": D("10")}, "high_covers_open_close", id="high-below-close"),
        pytest.param({"low": D("10.2")}, "low_covers_open_close", id="low-above-open"),
        pytest.param({"volume": -1}, "volume_non_negative", id="negative-volume"),
        pytest.param({"adj_close": D("0")}, "adj_close_positive", id="zero-adj-close"),
    ],
)
def test_bad_bars_are_rejected(
    db: Session,
    security: Security,
    run: IngestionRun,
    overrides: dict[str, Any],
    constraint: str,
) -> None:
    with rejected(db, f"ck_daily_prices_{constraint}"):
        db.add(make_bar(security, run, **overrides))
        db.flush()


def test_one_bar_per_security_per_day(db: Session, security: Security, run: IngestionRun) -> None:
    db.add(make_bar(security, run))
    db.flush()

    with rejected(db, "pk_daily_prices"):
        db.add(make_bar(security, run))
        db.flush()


def test_bar_must_reference_an_existing_security(db: Session, run: IngestionRun) -> None:
    with rejected(db, "fk_daily_prices_security_id_securities"):
        db.add(
            DailyPrice(
                security_id=999_999,
                trade_date=DAY,
                open=D("1"),
                high=D("1"),
                low=D("1"),
                close=D("1"),
                volume=0,
                ingestion_run_id=run.id,
            )
        )
        db.flush()


def test_security_with_prices_cannot_be_deleted(
    db: Session, security: Security, run: IngestionRun
) -> None:
    db.add(make_bar(security, run))
    db.flush()

    with rejected(db, "fk_daily_prices_security_id_securities"):
        db.delete(security)
        db.flush()


# --- Corporate Actions ---


def test_valid_split_and_dividend(db: Session, security: Security, run: IngestionRun) -> None:
    db.add(make_action(security, run, split_from=D("2"), split_to=D("3")))  # 3-for-2
    db.add(
        make_action(
            security,
            run,
            kind=CorporateActionKind.DIVIDEND,
            split_from=None,
            split_to=None,
            cash_amount=D("0.24"),
            currency="USD",
        )
    )
    db.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"cash_amount": D("1"), "currency": "USD"}, id="split-with-cash"),
        pytest.param({"split_to": D("0")}, id="zero-split-ratio"),
        pytest.param({"split_from": None}, id="split-missing-ratio"),
        pytest.param(
            {"kind": CorporateActionKind.DIVIDEND, "cash_amount": D("0.2"), "currency": "USD"},
            id="dividend-with-split-ratio",
        ),
        pytest.param(
            {
                "kind": CorporateActionKind.DIVIDEND,
                "split_from": None,
                "split_to": None,
                "cash_amount": D("0.2"),
            },
            id="dividend-missing-currency",
        ),
        pytest.param(
            {
                "kind": CorporateActionKind.DIVIDEND,
                "split_from": None,
                "split_to": None,
                "cash_amount": D("0"),
                "currency": "USD",
            },
            id="zero-dividend",
        ),
    ],
)
def test_corporate_action_fields_must_match_kind(
    db: Session, security: Security, run: IngestionRun, overrides: dict[str, Any]
) -> None:
    with rejected(db, "ck_corporate_actions_kind_fields_match"):
        db.add(make_action(security, run, **overrides))
        db.flush()


def test_duplicate_action_on_same_ex_date_is_rejected(
    db: Session, security: Security, run: IngestionRun
) -> None:
    db.add(make_action(security, run))
    db.flush()

    with rejected(db, "uq_corporate_actions_security_kind_ex_date"):
        db.add(make_action(security, run))
        db.flush()


def test_unknown_action_kind_is_rejected_even_bypassing_the_orm(
    db: Session, security: Security, run: IngestionRun
) -> None:
    # An unknown kind also fails kind_fields_match; Postgres reports whichever it evaluates first.
    with rejected(db, r"ck_corporate_actions_kind_(valid|fields_match)"):
        db.execute(
            text(
                "INSERT INTO corporate_actions (security_id, kind, ex_date, ingestion_run_id)"
                " VALUES (:sec, 'bogus', :day, :run)"
            ),
            {"sec": security.id, "day": DAY, "run": run.id},
        )


# --- Ingestion Bookkeeping ---


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"status": RunStatus.SUCCEEDED}, id="finished-status-without-finish-time"),
        pytest.param(
            {
                "started_at": datetime(2024, 1, 2, tzinfo=UTC),
                "finished_at": datetime(2024, 1, 3, tzinfo=UTC),
            },
            id="running-but-finished",
        ),
    ],
)
def test_run_status_must_agree_with_finish_time(db: Session, overrides: dict[str, Any]) -> None:
    with rejected(db, "ck_ingestion_runs_finished_matches_status"):
        db.add(IngestionRun(source="fixture", **overrides))
        db.flush()


def test_run_cannot_finish_before_it_starts(db: Session) -> None:
    with rejected(db, "ck_ingestion_runs_finished_after_started"):
        db.add(
            IngestionRun(
                source="fixture",
                status=RunStatus.SUCCEEDED,
                started_at=datetime(2024, 1, 2, tzinfo=UTC),
                finished_at=datetime(2024, 1, 1, tzinfo=UTC),
            )
        )
        db.flush()


def test_unknown_run_status_is_rejected_even_bypassing_the_orm(db: Session) -> None:
    with rejected(db, "ck_ingestion_runs_status_valid"):
        db.execute(
            text(
                "INSERT INTO ingestion_runs (source, status, finished_at)"
                " VALUES ('fixture', 'bogus', now())"
            )
        )


def test_item_window_must_be_ordered(db: Session, security: Security, run: IngestionRun) -> None:
    with rejected(db, "ck_ingestion_run_items_window_ordered"):
        db.add(
            IngestionRunItem(
                run_id=run.id,
                security_id=security.id,
                window_start=date(2024, 2, 1),
                window_end=date(2024, 1, 1),
            )
        )
        db.flush()


def test_item_counts_cannot_be_negative(db: Session, security: Security, run: IngestionRun) -> None:
    with rejected(db, "ck_ingestion_run_items_counts_non_negative"):
        db.add(
            IngestionRunItem(
                run_id=run.id,
                security_id=security.id,
                window_start=DAY,
                window_end=DAY,
                bars_written=-1,
            )
        )
        db.flush()


def test_deleting_a_run_deletes_its_items_and_issues(
    db: Session, security: Security, run: IngestionRun
) -> None:
    db.add(
        IngestionRunItem(
            run_id=run.id,
            security_id=security.id,
            window_start=DAY,
            window_end=DAY,
            status=ItemStatus.QUARANTINED,
        )
    )
    db.add(
        DataQualityIssue(
            run_id=run.id,
            security_id=security.id,
            trade_date=DAY,
            check_name="ohlc_consistency",
            severity=Severity.ERROR,
            message="high below close",
        )
    )
    db.flush()

    db.delete(run)
    db.flush()

    assert db.scalar(select(func.count()).select_from(IngestionRunItem)) == 0
    assert db.scalar(select(func.count()).select_from(DataQualityIssue)) == 0


def test_run_with_prices_cannot_be_deleted(
    db: Session, security: Security, run: IngestionRun
) -> None:
    db.add(make_bar(security, run))
    db.flush()

    with rejected(db, "fk_daily_prices_ingestion_run_id_ingestion_runs"):
        db.delete(run)
        db.flush()


def test_unknown_severity_is_rejected_even_bypassing_the_orm(
    db: Session, security: Security, run: IngestionRun
) -> None:
    with rejected(db, "ck_data_quality_issues_severity_valid"):
        db.execute(
            text(
                "INSERT INTO data_quality_issues"
                " (run_id, security_id, check_name, severity, message)"
                " VALUES (:run, :sec, 'x', 'bogus', 'm')"
            ),
            {"run": run.id, "sec": security.id},
        )
