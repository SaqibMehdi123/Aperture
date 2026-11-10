"""Operator library (spec 7.1, "Operator Library").

Seven operators behind the Operator protocol (spec Table 6, P1):
keep_recent, dedupe, summarize, pin_protected, cache_align,
subagent_isolation, semantic_retrieval. Every operator is pure
(apply -> WindowDiff) so the engine guardrail and the replay engine can audit
it; destructive intent is expressed only through `dropped_spans`.
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


def _load_builtins() -> None:
    from aperture.operators import (  # noqa: F401 - built-ins register on import
        cache_align,
        dedupe,
        keep_recent,
        pin_protected,
        semantic_retrieval,
        subagent_isolation,
        summarize,
    )


def registry() -> dict[str, Operator]:
    """Snapshot of the current registry (name -> operator)."""
    _load_builtins()
    return dict(_REGISTRY)


def get(name: str) -> Operator:
    _load_builtins()
    if name not in _REGISTRY:
        raise KeyError(f"unknown operator: {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


T = TypeVar("T")
