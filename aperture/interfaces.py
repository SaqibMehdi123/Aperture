"""Core interface contracts (spec Section 7.3).

These are the protocols every module programs against. Signatures follow the
dossier's shape notes; they are the stability promise for adapters, operators,
policies, and the benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple, Protocol, runtime_checkable

from aperture.session import Features, Window, WindowDiff


@dataclass(frozen=True)
class PlannedOp:
    """One operator invocation inside a plan (Appendix A `plan[]`)."""

    op: str
    params: dict[str, Any] = field(default_factory=dict)
    order: int = 0


class Reward(NamedTuple):
    """Per-step online update signal (spec 7.3). `cache_invalidation` prices AG1;
    `survival_penalty` prices AG2; the bandit update consumes all fields (AG4)."""

    task_progress: float
    cost_delta_usd: float
    cache_invalidation: int
    survival_penalty: float
    latency_ms: float


@runtime_checkable
class Operator(Protocol):
    """A composable context operator. Pure: `apply` returns a diff, it never
    mutates the window. Destructive effects are expressed only through
    `dropped_spans`, which the engine's guardrail can veto."""

    name: str

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        """Cheap estimate of execution cost (units: ~ms or work units)."""
        ...

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        ...


@runtime_checkable
class PolicySelector(Protocol):
    """Chooses the operator plan per step; updated online per step (spec 7.3)."""

    def select(self, f: Features) -> list[PlannedOp]:
        """ops + params + order."""
        ...

    def update(self, r: Reward) -> None:
        """Online update; fixed arms accept and ignore."""
        ...

    def fallback(self) -> list[PlannedOp]:
        """Tuned fixed heuristic used under uncertainty or drift."""
        ...
