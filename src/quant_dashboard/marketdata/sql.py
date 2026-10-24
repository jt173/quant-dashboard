from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_dashboard.models import CorporateAction, CorporateActionKind, DailyPrice, Security

from .adjustment import dividend_factors
from .repository import AmbiguousSecurityError, UnknownSecurityError
from .types import AdjustedBar

_SIX_DP = Decimal("0.000001")


class SqlPriceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_prices(
        self,
        ticker: str,
        *,
        start: date | None = None,
        end: date | None = None,
        mic: str | None = None,
    ) -> list[AdjustedBar]:
        security_id = self._resolve(ticker, mic)

        # Always load the full history: dividend after the window and closes
        # before it both feed the factors. ~3k rows per ticker, so cheap enough
        rows = self._session.execute(
            select(
                DailyPrice.trade_date,
                DailyPrice.open,
                DailyPrice.high,
                DailyPrice.low,
                DailyPrice.close,
                DailyPrice.volume,
            )
            .where(DailyPrice.security_id == security_id)
            .order_by(DailyPrice.trade_date)
        ).all()
        dividends = self._session.execute(
            select(CorporateAction.ex_date, CorporateAction.cash_amount)
            .where(
                CorporateAction.security_id == security_id,
                CorporateAction.kind == CorporateActionKind.DIVIDEND,
            )
            .order_by(CorporateAction.ex_date)
        ).all()

        factors = dividend_factors(
            [(r.trade_date, r.close) for r in rows],
            [(d.ex_date, d.cash_amount) for d in dividends if d.cash_amount is not None],
        )

        return [
            AdjustedBar(
                trade_date=r.trade_date,
                open=r.open,
                high=r.high,
                low=r.low,
                close=r.close,
                volume=r.volume,
                adj_factor=f,
                adj_close=(r.close * f).quantize(_SIX_DP),
            )
            for r, f in zip(rows, factors, strict=True)
            if (start is None or r.trade_date >= start) and (end is None or r.trade_date <= end)
        ]

    def get_prices_many(
        self,
        tickers: Sequence[str],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, list[AdjustedBar]]:
        return {t: self.get_prices(t, start=start, end=end) for t in tickers}

    def _resolve(self, ticker: str, mic: str | None) -> int:
        stmt = select(Security.id).where(Security.ticker == ticker)
        if mic is not None:
            stmt = stmt.where(Security.mic == mic)
        ids = self._session.scalars(stmt).all()
        if not ids:
            raise UnknownSecurityError(f"unknown security {ticker!r}")
        if len(ids) > 1:
            raise AmbiguousSecurityError(f"{ticker!r} matches {len(ids)} listings; pass mic")
        return ids[0]
