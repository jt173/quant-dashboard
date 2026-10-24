from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

from .quality import check_daily_data
from .source import MarketDataSource, SourceError
from .types import DailyData

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SecuritySpec:
    ticker: str
    mic: str
    currency: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class _Work:
    """Plain-value snapshot of one run item, safe to use after a rollback."""

    security_id: int
    ticker: str
    currency: str
    window_start: date
    window_end: date  # inclusive


def ensure_securities(session: Session, specs: Sequence[SecuritySpec]) -> list[Security]:
    securities: list[Security] = []
    for spec in specs:
        security = session.scalar(
            select(Security).where(Security.ticker == spec.ticker, Security.mic == spec.mic)
        )
        if security is None:
            security = Security(
                ticker=spec.ticker, mic=spec.mic, currency=spec.currency, name=spec.name
            )
            session.add(security)
        securities.append(security)
    session.commit()
    return securities


def plan_run(
    session: Session,
    *,
    source_name: str,
    securities: Sequence[Security],
    default_start: date,
    end: date,
    overlap_days: int = 7,
) -> int:
    """
    Create a run plus one item per security. Windows are derived from stored data.

    The overlap re-fetches recent days so late corrections (and yesterday's
    possibly-partial bar) get overwritten by the upsert.
    """
    run = IngestionRun(
        source=source_name,
        params={
            "default_start": default_start.isoformat(),
            "end": end.isoformat(),
            "overlap_days": overlap_days,
            "tickers": [s.ticker for s in securities],
        },
    )
    session.add(run)
    session.flush()
    run_id = run.id

    for security in securities:
        earliest, latest = session.execute(
            select(func.min(DailyPrice.trade_date), func.max(DailyPrice.trade_date)).where(
                DailyPrice.security_id == security.id
            )
        ).one()
        # Backfill when history doesn't reach back to default_start.
        # The tolerance absorbs weekends/holidays
        if earliest is None or latest is None or earliest > default_start + timedelta(days=7):
            start = default_start
        else:
            start = max(default_start, latest - timedelta(days=overlap_days))
        if start > end:
            continue
        session.add(
            IngestionRunItem(
                run_id=run_id, security_id=security.id, window_start=start, window_end=end
            )
        )
    session.commit()
    return run_id


def execute_run(session: Session, source: MarketDataSource, run_id: int) -> RunStatus:
    """
    Process every pending/failed item of a run. Safe to call again on resume.

    Quarantined items are not retired: the same data would fail the same checks.
    """
    if session.get(IngestionRun, run_id) is None:
        raise ValueError(f"no ingestion run {run_id}")

    # A run is 'running' exactly when finished_at is NULL
    session.execute(
        update(IngestionRun)
        .where(IngestionRun.id == run_id)
        .values(status=RunStatus.RUNNING, finished_at=None)
    )
    session.commit()

    rows = session.execute(
        select(IngestionRunItem, Security)
        .join(Security, Security.id == IngestionRunItem.security_id)
        .where(
            IngestionRunItem.run_id == run_id,
            IngestionRunItem.status.in_([ItemStatus.PENDING, ItemStatus.FAILED]),
        )
        .order_by(Security.ticker)
    ).all()
    work = [
        _Work(s.id, s.ticker, s.currency, item.window_start, item.window_end) for item, s in rows
    ]

    for w in work:
        _process_item(session, source, run_id, w)

    return _finalize(session, run_id)


def _process_item(session: Session, source: MarketDataSource, run_id: int, w: _Work) -> None:
    try:
        end_exclusive = w.window_end + timedelta(days=1)
        earliest = session.scalar(
            select(func.min(DailyPrice.trade_date)).where(DailyPrice.security_id == w.security_id)
        )
        data = source.fetch_daily(w.ticker, w.window_start, end_exclusive)

        # Yahoo restates the whole history when a split happens
        # An incremental window would leave older rows at the pre-split scale
        # so refresh it all
        if (
            earliest is not None
            and earliest < w.window_start
            and _has_unseen_split(session, w.security_id, data)
        ):
            log.info("%s: new split, refreshing history from %s", w.ticker, earliest)
            data = source.fetch_daily(w.ticker, earliest, end_exclusive)

        if not data.bars and earliest is None:
            raise SourceError(f"no data returned for {w.ticker} (bad symbol?)")

        issues = check_daily_data(data)
        session.execute(
            delete(DataQualityIssue).where(
                DataQualityIssue.run_id == run_id,
                DataQualityIssue.security_id == w.security_id,
            )
        )
        session.add_all(
            DataQualityIssue(
                run_id=run_id,
                security_id=w.security_id,
                trade_date=i.trade_date,
                check_name=i.code,
                severity=i.severity,
                message=i.message,
            )
            for i in issues
        )

        errors = [i for i in issues if i.severity is Severity.ERROR]
        if errors:
            codes = ", ".join(sorted({i.code for i in errors}))
            _set_item(
                session,
                run_id,
                w,
                status=ItemStatus.QUARANTINED,
                error=f"{len(errors)} data quality error(s): {codes}",
            )
            session.commit()
            log.warning("%s: quarantined (%s)", w.ticker, codes)
            return

        bars_written = _upsert_prices(session, run_id, w, data)
        actions_written = _upsert_actions(session, run_id, w, data)
        _set_item(
            session,
            run_id,
            w,
            status=ItemStatus.SUCCEEDED,
            bars_written=bars_written,
            actions_written=actions_written,
            error=None,
        )
        session.commit()
        log.info("%s: %d bars, %d actions", w.ticker, bars_written, actions_written)
    except Exception as exc:
        session.rollback()
        log.exception("%s: ingestion failed", w.ticker)
        _set_item(session, run_id, w, status=ItemStatus.FAILED, error=str(exc))
        session.commit()


def _has_unseen_split(session: Session, security_id: int, data: DailyData) -> bool:
    if not data.splits:
        return False
    stored = set(
        session.scalars(
            select(CorporateAction.ex_date).where(
                CorporateAction.security_id == security_id,
                CorporateAction.kind == CorporateActionKind.SPLIT,
            )
        )
    )
    return any(s.ex_date not in stored for s in data.splits)


def _set_item(session: Session, run_id: int, w: _Work, **values: object) -> None:
    session.execute(
        update(IngestionRunItem)
        .where(
            IngestionRunItem.run_id == run_id,
            IngestionRunItem.security_id == w.security_id,
            IngestionRunItem.window_start == w.window_start,
        )
        .values(**values)
    )


def _upsert_prices(session: Session, run_id: int, w: _Work, data: DailyData) -> int:
    rows = [
        {
            "security_id": w.security_id,
            "trade_date": b.trade_date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "adj_close": b.adj_close,
            "ingestion_run_id": run_id,
        }
        for b in data.bars
    ]
    if not rows:
        return 0
    stmt = pg_insert(DailyPrice)
    stmt = stmt.on_conflict_do_update(
        index_elements=["security_id", "trade_date"],
        set_={
            c: stmt.excluded[c]
            for c in ("open", "high", "low", "close", "volume", "adj_close", "ingestion_run_id")
        },
    )
    session.execute(stmt, rows)
    return len(rows)


def _split_terms(ratio: Decimal) -> tuple[Decimal, Decimal]:
    """Yahoo ratio (2 = 2-for-1, 0.1 = 1-for-10) -> (split_from, split_to)"""
    if ratio >= 1:
        return Decimal(1), ratio
    # Inverse rounded to 4dp so 0.333333 comes back as 3, not 3.000003
    return (Decimal(1) / ratio).quantize(Decimal("0.0001")), Decimal(1)


def _upsert_actions(session: Session, run_id: int, w: _Work, data: DailyData) -> int:
    written = 0

    dividend_rows = [
        {
            "security_id": w.security_id,
            "kind": CorporateActionKind.DIVIDEND,
            "ex_date": d.ex_date,
            "cash_amount": d.amount,
            "currency": w.currency,
            "ingestion_run_id": run_id,
        }
        for d in data.dividends
    ]
    if dividend_rows:
        stmt = pg_insert(CorporateAction)
        stmt = stmt.on_conflict_do_update(
            index_elements=["security_id", "kind", "ex_date"],
            set_={
                "cash_amount": stmt.excluded.cash_amount,
                "ingestion_run_id": stmt.excluded.ingestion_run_id,
            },
        )
        session.execute(stmt, dividend_rows)
        written += len(dividend_rows)

    split_rows = []
    for s in data.splits:
        split_from, split_to = _split_terms(s.ratio)
        split_rows.append(
            {
                "security_id": w.security_id,
                "kind": CorporateActionKind.SPLIT,
                "ex_date": s.ex_date,
                "split_from": split_from,
                "split_to": split_to,
                "ingestion_run_id": run_id,
            }
        )
    if split_rows:
        stmt = pg_insert(CorporateAction)
        stmt = stmt.on_conflict_do_update(
            index_elements=["security_id", "kind", "ex_date"],
            set_={
                "split_from": stmt.excluded.split_from,
                "split_to": stmt.excluded.split_to,
                "ingestion_run_id": stmt.excluded.ingestion_run_id,
            },
        )
        session.execute(stmt, split_rows)
        written += len(split_rows)

    return written


def _finalize(session: Session, run_id: int) -> RunStatus:
    counts = Counter(
        session.scalars(select(IngestionRunItem.status).where(IngestionRunItem.run_id == run_id))
    )
    total = sum(counts.values())
    succeeded = counts[ItemStatus.SUCCEEDED]
    if succeeded == total:
        status = RunStatus.SUCCEEDED
    elif succeeded == 0:
        status = RunStatus.FAILED
    else:
        status = RunStatus.PARTIAL

    session.execute(
        update(IngestionRun)
        .where(IngestionRun.id == run_id)
        .values(status=status, finished_at=func.now())
    )
    session.commit()
    return status
