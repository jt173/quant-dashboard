from __future__ import annotations

import math
from datetime import date
from decimal import Decimal

import yfinance as yf

from .source import SourceError
from .types import DailyData, Dividend, PriceBar, Split

_PRICE_COLS = ["Open", "High", "Low", "Close", "Adj Close"]


def _dec(value: float) -> Decimal:
    # Yahoo returns float32-ish artifacts. Round before decimal.
    return Decimal(str(round(float(value), 6)))


class YahooSource:
    name = "yahoo"

    def fetch_daily(self, symbol: str, start: date, end: date | None = None) -> DailyData:
        try:
            df = yf.Ticker(symbol).history(
                start=start.isoformat(),
                end=end.isoformat() if end is not None else None,
                interval="1d",
                auto_adjust=False,  # we want raw close and adj close
                actions=True,
            )
        except Exception as exc:  # yfinance raises multiple exception types
            raise SourceError(f"Yahoo fetch failed for {symbol}: {exc}") from exc

        if df.empty:
            return DailyData(symbol=symbol)

        records = df.to_dict("records")
        dates = [ts.date() for ts in df.index]

        dividends = tuple(
            Dividend(ex_date=d, amount=_dec(r["Dividends"]))
            for d, r in zip(dates, records, strict=True)
            if r["Dividends"] > 0
        )
        splits = tuple(
            Split(ex_date=d, ratio=_dec(r["Stock Splits"]))
            for d, r in zip(dates, records, strict=True)
            if r["Stock Splits"] > 0
        )

        bars: list[PriceBar] = []
        for d, r in zip(dates, records, strict=True):
            if any(math.isnan(r[c]) for c in _PRICE_COLS):
                continue  # incomplete row
            volume = 0 if math.isnan(r["Volume"]) else int(r["Volume"])
            bars.append(
                PriceBar(
                    trade_date=d,
                    open=_dec(r["Open"]),
                    high=_dec(r["High"]),
                    low=_dec(r["Low"]),
                    close=_dec(r["Close"]),
                    adj_close=_dec(r["Adj Close"]),
                    volume=volume,
                )
            )

        return DailyData(symbol=symbol, bars=tuple(bars), dividends=dividends, splits=splits)
