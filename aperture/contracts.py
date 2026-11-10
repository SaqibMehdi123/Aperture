"""AG5 groundwork: typed Context Contracts for multi-agent handoffs (spec 6.5,
7.3). A contract makes a handoff budgeted, class-restricted, and expirable so
spawned subagents cannot balloon the parent's context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple


class ContextContract(NamedTuple):
    """Typed handoff contract (spec 7.3)."""

    task_id: str
    objective: str
    token_budget: int
    allowed_classes: frozenset[str]
    ttl_steps: int
    provenance: tuple[str, ...]
    return_schema: str


@dataclass
class ContractRegistry:
    """Registers contracts and expires them by TTL (steps)."""

    _contracts: dict[str, ContextContract] = field(default_factory=dict)
    _born_step: dict[str, int] = field(default_factory=dict)

    def register(self, contract: ContextContract, step: int = 0) -> None:
        self._contracts[contract.task_id] = contract
        self._born_step[contract.task_id] = step

    def get(self, task_id: str) -> ContextContract | None:
        return self._contracts.get(task_id)

    def active(self, step: int) -> list[ContextContract]:
        """Contracts whose TTL has not expired at `step`."""
        out = []
        for task_id, contract in self._contracts.items():
            if step - self._born_step[task_id] <= contract.ttl_steps:
                out.append(contract)
        return out

    def validate_window(self, contract: ContextContract, window) -> list[str]:
        """Return violations of the contract against a window (empty = valid)."""
        violations: list[str] = []
        if window.total_tokens() > contract.token_budget:
            violations.append(f"budget: {window.total_tokens()} > {contract.token_budget}")
        for span in window.spans:
            if span.span_class not in contract.allowed_classes:
                violations.append(
                    f"class: span {span.span_id} has class {span.span_class!r} "
                    f"not in allowed {sorted(contract.allowed_classes)}"
                )
        return violations
