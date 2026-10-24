import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from quant_dashboard.db import Base

# --- Reusable column types ---

Price = Annotated[Decimal, mapped_column(Numeric(18, 6))]
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]
IntPk = Annotated[int, mapped_column(Integer, Identity(), primary_key=True)]


def _enum(cls: type[enum.Enum]) -> Enum:
    """
    Store an enum as plain VARCHAR; pair it with '_one_of' so the database enforces the values.
    A CHECK constraint is easier to evolve than a native Postgres ENUM type.
    """
    return Enum(
        cls,
        native_enum=False,
        length=16,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


def _one_of(column: str, cls: type[enum.Enum]) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in cls)
    return CheckConstraint(f"{column} IN ({values})", name=f"{column}_valid")


class CorporateActionKind(enum.StrEnum):
    SPLIT = "split"
    DIVIDEND = "dividend"


class RunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # finished, but some items failed
    FAILED = "failed"


class ItemStatus(enum.StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    QUARANTINED = "quarantined"  # data quality errors blocked the write


class Severity(enum.StrEnum):
    WARNING = "warning"
    ERROR = "error"


# --- Reference data ---
class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("ticker", "mic", name="ticker_mic"),
        CheckConstraint("char_length(currency) = 3", name="currency_iso_length"),
        CheckConstraint(
            "delisted_on IS NULL OR listed_on IS NULL OR delisted_on >= listed_on",
            name="delisted_after_listed",
        ),
    )

    # The surrogate key is the identity; ticker and mic are attributes
    id: Mapped[IntPk]
    ticker: Mapped[str] = mapped_column(String(32))
    mic: Mapped[str] = mapped_column(String(4))  # ISO 10383 market identifier
    name: Mapped[str | None] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(server_default="true")
    listed_on: Mapped[date | None] = mapped_column(Date)
    delisted_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[Timestamp] = mapped_column(server_default=func.now())


# --- Ingestion bookkeeping ---
class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        _one_of("status", RunStatus),
        CheckConstraint("finished_at >= started_at", name="finished_after_started"),
        # A run is 'running' exactly when it has not finished
        CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name="finished_matches_status"
        ),
    )

    id: Mapped[IntPk]
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus), server_default=RunStatus.RUNNING.value
    )
    started_at: Mapped[Timestamp] = mapped_column(server_default=func.now())
    finished_at: Mapped[Timestamp | None]
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)


class IngestionRunItem(Base):
    """One unit of work in a run: a (security, data window). Resuming retries unfinished items"""

    __tablename__ = "ingestion_run_items"
    __table_args__ = (
        _one_of("status", ItemStatus),
        CheckConstraint("window_end >= window_start", name="window_ordered"),
        CheckConstraint("bars_written >= 0 AND actions_written >= 0", name="counts_non_negative"),
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), primary_key=True
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    window_start: Mapped[date] = mapped_column(Date, primary_key=True)
    window_end: Mapped[date] = mapped_column(Date)
    status: Mapped[ItemStatus] = mapped_column(
        _enum(ItemStatus), server_default=ItemStatus.PENDING.value
    )
    bars_written: Mapped[int] = mapped_column(server_default="0")
    actions_written: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None] = mapped_column(Text)


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (_one_of("severity", Severity),)

    id: Mapped[IntPk]
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"), index=True
    )
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"))
    trade_date: Mapped[date | None] = mapped_column(Date)
    check_name: Mapped[str] = mapped_column(String(64))
    severity: Mapped[Severity] = mapped_column(_enum(Severity))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[Timestamp] = mapped_column(server_default=func.now())


# --- Market Data ---
class DailyPrice(Base):
    """Daily OHLCV bar exacly as the provider reported it"""

    __tablename__ = "daily_prices"
    __table_args__ = (
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="prices_positive"),
        CheckConstraint("high >= open AND high >= close", name="high_covers_open_close"),
        CheckConstraint("low <= open AND low <= close", name="low_covers_open_close"),
        CheckConstraint("volume >= 0", name="volume_non_negative"),
        # NULL passes a CHECK, so this only constrains adj_close when it is present
        CheckConstraint("adj_close > 0", name="adj_close_positive"),
    )

    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    open: Mapped[Price]
    high: Mapped[Price]
    low: Mapped[Price]
    close: Mapped[Price]
    volume: Mapped[int] = mapped_column(BigInteger)
    adj_close: Mapped[Price | None]  # provider's adjusted close, kept only as a cross-check
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        _one_of("kind", CorporateActionKind),
        UniqueConstraint("security_id", "kind", "ex_date", name="security_kind_ex_date"),
        # Exactly the columns that belong to each kind are populated, and nothing else.
        # The explicit IS NOT NULLs matter: a CHECK that evaluates to NULL counts as passing.
        CheckConstraint(
            "(kind = 'split' AND split_from IS NOT NULL AND split_to IS NOT NULL"
            " AND split_from > 0 AND split_to > 0"
            " AND cash_amount IS NULL AND currency IS NULL)"
            " OR (kind = 'dividend' AND cash_amount IS NOT NULL AND cash_amount > 0"
            " AND currency IS NOT NULL AND split_from IS NULL AND split_to IS NULL)",
            name="kind_fields_match",
        ),
    )

    id: Mapped[IntPk]
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"))
    kind: Mapped[CorporateActionKind] = mapped_column(_enum(CorporateActionKind))
    ex_date: Mapped[date] = mapped_column(Date)
    # A 4-for-1 split is split_from=1, split_to=4; a 1-for-10 reverse split is from=10, to=1.
    split_from: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    split_to: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    cash_amount: Mapped[Price | None]
    currency: Mapped[str | None] = mapped_column(String(3))
    ingestion_run_id: Mapped[int] = mapped_column(ForeignKey("ingestion_runs.id"), index=True)
