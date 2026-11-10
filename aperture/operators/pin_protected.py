"""pin_protected: mark constraint-like content pinned + protected (AG2).

Non-destructive: the operator's entire effect is flag annotations. Content is
flagged when (a) its class is `constraint`, or (b) it matches governance
language heuristics ("must", "never", "POLICY:", ...). Once flagged, the
engine's guardrail vetoes any later drop - even from adversarial operators -
so governance constraints survive curation by construction.
"""

from __future__ import annotations

import re
from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.session import Features, PinUpdate, Window, WindowDiff

SPAN_CONSTRAINT = "constraint"

DEFAULT_PATTERNS: tuple[str, ...] = (
    r"\b(must|must not|never|always|do not|don't|cannot|can't)\b",
    r"\b(required|forbidden|mandatory|prohibited)\b",
    r"\b(policy|policies|constraint|constraints|compliance|gdpr|hipaa|soc2)\b",
    r"\b(escalat\w+|prior approval|authorized user only)\b",
)


@register
class PinProtected:
    name = "pin_protected"

    def __init__(self, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> None:
        self._patterns = patterns

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return len(window.spans)

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        extra = tuple(params.get("extra_patterns", ()))
        max_spans = int(params.get("max_spans", 32))
        compiled = [re.compile(p, re.IGNORECASE) for p in self._patterns + extra]

        annotations: list[PinUpdate] = []
        for span in window.spans:
            if len(annotations) >= max_spans:
                break
            if span.pinned and span.protected:
                continue  # already safe: idempotent, no duplicate log entries
            if span.span_class == SPAN_CONSTRAINT or any(c.search(span.content) for c in compiled):
                annotations.append(PinUpdate(span_id=span.span_id, pinned=True, protected=True))

        return WindowDiff(
            op=self.name,
            kept_spans=tuple(s.span_id for s in window.spans),
            cache_head_unchanged=True,
            pinned=tuple(annotations),
        )
