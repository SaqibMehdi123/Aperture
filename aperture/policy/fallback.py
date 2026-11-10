"""Policy selector: fixed-heuristic arm (spec 7.3 `PolicySelector`).

The safe default shape: no curation while the budget is comfortable,
`keep_recent` when it is not, `dedupe` when redundancy is visible. The
knobs below are grid-searched offline by `eval/tune.py` on the deterministic
task suite (`eval/tasks.py`); the shipped defaults carry the winning values.
Phase P3 adds the online bandit alongside this arm.
"""

from __future__ import annotations

from aperture.interfaces import PlannedOp, Reward
from aperture.session import Features


class HeuristicSelector:
    """Fixed heuristic arm ("aperture_fixed").

    Knobs (tuned offline, see `eval/tune.py`):

    - `threshold`: plan `keep_recent` once `budget_used_frac >= threshold`.
    - `keep_n`: how many recent droppable spans keep_recent retains.
    - `dedupe_at`: plan `dedupe` when `redundancy_score >= dedupe_at`;
      the default 1.1 disables dedupe (redundancy never reaches it).
    """

    def __init__(self, threshold: float = 0.7, keep_n: int = 12, dedupe_at: float = 1.1) -> None:
        self.threshold = threshold
        self.keep_n = keep_n
        self.dedupe_at = dedupe_at
        self.updates = 0

    def select(self, f: Features) -> list[PlannedOp]:
        plan: list[PlannedOp] = []
        if f.redundancy_score >= self.dedupe_at:
            plan.append(PlannedOp(op="dedupe", params={}, order=len(plan)))
        if f.budget_used_frac >= self.threshold:
            plan.append(
                PlannedOp(op="keep_recent", params={"keep_n": self.keep_n}, order=len(plan))
            )
        return plan

    def update(self, r: Reward) -> None:
        self.updates += 1  # fixed arms log the reward but do not adapt

    def fallback(self) -> list[PlannedOp]:
        return [PlannedOp(op="keep_recent", params={"keep_n": self.keep_n}, order=0)]
