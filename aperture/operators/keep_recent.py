"""keep_recent: keep the cache head plus the N most recent droppable spans.

The P0 reference operator for the runtime machinery (weeks 7-8 add summarize
and dedupe beside it). It is destructive, so it exercises the guardrail: it
never drops pinned or protected spans even if params ask for it, and it never
touches the cache-stable head (cache_head_unchanged stays true).
"""

from __future__ import annotations

from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.session import Features, Span, Window, WindowDiff


@register
class KeepRecent:
    name = "keep_recent"

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return len(window.spans)

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        keep_n = max(0, int(params.get("keep_n", 10)))
        tail = [s for s in window.spans if not s.cache_head]
        droppable = [s for s in tail if not (s.pinned or s.protected)]

        # Oldest droppable spans beyond the last `keep_n` are dropped.
        overflow = droppable[:-keep_n] if keep_n < len(droppable) else []
        drop_ids = {s.span_id for s in overflow}

        if not drop_ids:
            kept = tuple(s.span_id for s in window.spans)
            return WindowDiff(op=self.name, kept_spans=kept, cache_head_unchanged=True)

        dropped = tuple(
            _drop_record(s, "keep_recent overflow") for s in window.spans if s.span_id in drop_ids
        )
        kept = tuple(s.span_id for s in window.spans if s.span_id not in drop_ids)
        # Constraint-class drops become survival-probe targets (AG2).
        probe_targets = tuple(
            s.span_id for s in overflow if s.span_class == "constraint"
        )
        return WindowDiff(
            op=self.name,
            kept_spans=kept,
            dropped_spans=dropped,
            cache_head_unchanged=True,
            probe_targets=probe_targets,
        )


def _drop_record(span: Span, reason: str):
    from aperture.session import DroppedSpan

    return DroppedSpan(
        span_id=span.span_id,
        reason=reason,
        bytes=span.bytes,
        classes=(span.span_class,),
    )
