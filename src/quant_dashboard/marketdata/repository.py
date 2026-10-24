from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from .types import AdjustedBar


class UnknownSecurityError(LookupError):
    """No security matches the requested ticker (and mic, if given)"""


class AmbiguousSecurityError(LookupError):
    """The ticker matches several listings; pass 'mic' to disambiguate"""


class PriceRepository(Protocol):
    def get_prices(
        self,
        ticker: str,
        *,
        start: date | None = None,
        end: date | None = None,
        mic: str | None = None,
    ) -> list[AdjustedBar]:
        """
        Bars ascending by date, with start and end both inclusive.

        Adjustment factors are anchored to the latest stored bar,
        regardless of the requested window, so a value for a given date
        doesn't depend on how you sliced the query.
        """
        ...

    def get_prices_many(
        self,
        tickers: Sequence[str],
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> dict[str, list[AdjustedBar]]: ...
