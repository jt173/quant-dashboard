"""Constraints shared by all optimizers. Weights always sum to 1"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Constraints:
    """Fully invested is implicit (weights sum to 1)

    long_only: weights >= 0.
    max_weight: cap on each weight. With long_only=False it caps absolute
        weight (-maxweight <= w <= max_weight)
    """

    long_only: bool = True
    max_weight: float | None = None

    def __post_init__(self) -> None:
        if self.max_weight is not None and not 0.0 < self.max_weight <= 1.0:
            raise ValueError(f"max_weight must be in (0, 1], got {self.max_weight}")

    def bounds(self, n_assets: int) -> tuple[float | None, float | None]:
        """(lower, upper) bound applied to every weight; None means unbounded"""
        if (
            self.long_only
            and self.max_weight is not None
            and self.max_weight * n_assets < 1.0 - 1e-12
        ):
            raise ValueError(
                f"Infeasable: {n_assets} assets capped at {self.max_weight} cannot sum to 1"
            )
        lower = 0.0 if self.long_only else None if self.max_weight is None else -self.max_weight
        return lower, self.max_weight


DEFAULT_CONSTRAINTS = Constraints()
