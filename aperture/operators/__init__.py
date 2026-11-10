"""Operator library (spec 7.1, "Operator Library").

Seven operators are planned across Phases P0-P4: keep_recent, semantic_retrieval,
summarize, dedupe, subagent_isolation, pin_protected, cache_align. Phase P0 seeds
the registry and keep_recent; each operator is pure (apply -> WindowDiff) so the
engine guardrail and the replay engine can audit it.
"""

from __future__ import annotations

from typing import TypeVar

from aperture.interfaces import Operator

_REGISTRY: dict[str, Operator] = {}


def register(op: type) -> type:
    """Class decorator: add an Operator to the runtime registry."""
    instance = op()
    _REGISTRY[instance.name] = instance  # type: ignore[attr-defined]
    return op


def registry() -> dict[str, Operator]:
    """Snapshot of the current registry (name -> operator)."""
    from aperture.operators import keep_recent  # noqa: F401 - ensure built-ins register

    return dict(_REGISTRY)


def get(name: str) -> Operator:
    if name not in _REGISTRY:
        from aperture.operators import keep_recent  # noqa: F401 - ensure built-ins register

    if name not in _REGISTRY:
        raise KeyError(f"unknown operator: {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available() -> list[str]:
    from aperture.operators import keep_recent  # noqa: F401 - ensure built-ins register

    return sorted(_REGISTRY)


T = TypeVar("T")
