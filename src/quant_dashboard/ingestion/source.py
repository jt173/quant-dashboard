from __future__ import annotations

from datetime import date
from typing import Protocol

from .types import DailyData


class SourceError(Exception):
    """The upstream provider failed (network, rate limit, malformed response)."""


class MarketDataSource(Protocol):
    name: str

    def fetch_daily(self, symbol: str, start: date, end: date | None = None) -> DailyData:
        """Daily bars plus corporate actions for [start, end).

        'end' is exclusive. An empty result is valid. Raises SourceError on failure.
        """
        ...
