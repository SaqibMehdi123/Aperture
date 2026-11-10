"""Protected-class metadata (AG2 groundwork, spec 6.2/7.2 step 2).

Governance content must survive curation even when an adapter or operator
forgets to flag it. A protected class does this at the CLASS level: the
guardrail consults this registry before honoring any drop, so `constraint`
spans (and any class a project registers) can never be silently destroyed.

This is the mechanism behind the report's constraint-survival guarantee
("governance decay: 100% constraint survival"): protection is a property of
the runtime, not of individual operators.
"""

from __future__ import annotations


class ProtectedClasses:
    """Registry of span classes the guardrail always protects."""

    def __init__(self, defaults: tuple[str, ...] = ("constraint",)) -> None:
        self._protected: set[str] = set(defaults)

    def register(self, span_class: str) -> None:
        """Protect a whole class (e.g. 'audit_log', 'policy')."""
        self._protected.add(span_class)

    def unregister(self, span_class: str) -> None:
        self._protected.discard(span_class)

    def is_protected(self, span_class: str) -> bool:
        return span_class in self._protected

    def classes(self) -> frozenset[str]:
        return frozenset(self._protected)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ProtectedClasses({sorted(self._protected)})"
