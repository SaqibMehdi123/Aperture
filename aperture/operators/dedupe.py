"""dedupe: drop duplicate content spans, keep one occurrence.

Duplicate tool outputs and repeated notices are the cheapest waste in agent
windows. Matching normalizes whitespace and case; short conversational turns
("ok", "yes") are skipped by `min_tokens` so dialogue rhythm is preserved.
Pure: returns a diff; the guardrail still vetoes anything pinned/protected.
"""

from __future__ import annotations

from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.operators.common import drop_record, droppable
from aperture.session import Features, Window, WindowDiff


def _normalize(text: str) -> str:
    return " ".join(text.split()).lower()


@register
class Dedupe:
    name = "dedupe"

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return len(window.spans)

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        keep = str(params.get("keep", "last"))
        min_tokens = int(params.get("min_tokens", 16))
        if keep not in ("last", "first"):
            raise ValueError(f"dedupe keep must be 'last' or 'first', got {keep!r}")

        candidates = [s for s in droppable(window) if s.tokens >= min_tokens]
        groups: dict[str, list] = {}
        for s in candidates:
            groups.setdefault(_normalize(s.content), []).append(s)

        drop_ids: dict[str, str] = {}  # span_id -> reason
        for members in groups.values():
            if len(members) < 2:
                continue
            kept = members[-1] if keep == "last" else members[0]
            for s in members:
                if s.span_id != kept.span_id:
                    drop_ids[s.span_id] = f"dedupe duplicate (kept {kept.span_id})"

        if not drop_ids:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        dropped = tuple(
            drop_record(s, drop_ids[s.span_id]) for s in window.spans if s.span_id in drop_ids
        )
        kept = tuple(s.span_id for s in window.spans if s.span_id not in drop_ids)
        return WindowDiff(
            op=self.name,
            kept_spans=kept,
            dropped_spans=dropped,
            cache_head_unchanged=True,
        )
