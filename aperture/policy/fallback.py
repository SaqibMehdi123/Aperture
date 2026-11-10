"""Policy selector: fixed-heuristic seed (spec 7.3 `PolicySelector`).

Phase P0 ships the safe default: no curation while the budget is comfortable,
`keep_recent` when it is not. Phase P2 tunes this arm; Phase P3 adds the
online bandit alongside it.
"""

from __future__ import annotations

from aperture.interfaces import PlannedOp, Reward
from aperture.session import Features


class HeuristicSelector:
    """Fixed heuristic arm ("aperture_fixed"): threshold-triggered keep_recent."""

    def __init__(self, threshold: float = 0.7, keep_n: int = 12) -> None:
        self.threshold = threshold
        self.keep_n = keep_n
        self.updates = 0

    def select(self, f: Features) -> list[PlannedOp]:
        if f.budget_used_frac < self.threshold:
            return []
        return [PlannedOp(op="keep_recent", params={"keep_n": self.keep_n}, order=0)]

    def update(self, r: Reward) -> None:
        self.updates += 1  # fixed arms log the reward but do not adapt

    def fallback(self) -> list[PlannedOp]:
        return [PlannedOp(op="keep_recent", params={"keep_n": self.keep_n}, order=0)]
