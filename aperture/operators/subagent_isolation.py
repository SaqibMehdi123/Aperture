"""subagent_isolation: move bulky tool outputs out of the live window.

The pattern mirrors the report's subagent isolation proposal (spec 6.5): a
tool result that would dominate the window is replaced by a compact stub that
keeps its identity and size; the full body is archived by the runtime (every
drop is archived - see Session.complete) and can be pulled back with
semantic_retrieval. Pure: the operator only describes the swap.
"""

from __future__ import annotations

from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.operators.common import drop_record
from aperture.session import Features, NewSpan, Window, WindowDiff

DEFAULT_CLASSES = ("tool_result",)


@register
class SubagentIsolation:
    name = "subagent_isolation"

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return 2

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        min_bytes = int(params.get("min_bytes", 1024))
        max_spans = int(params.get("max_spans", 2))
        classes = tuple(params.get("classes", DEFAULT_CLASSES))

        candidates = [
            s
            for s in window.spans
            if not s.cache_head
            and not (s.pinned or s.protected)
            and s.span_class in classes
            and s.bytes >= min_bytes
        ]
        candidates.sort(key=lambda s: s.bytes, reverse=True)
        candidates = candidates[:max_spans]
        if not candidates:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        dropped_ids = {s.span_id for s in candidates}
        stubs = []
        for s in candidates:
            content = (
                f"[tool output archived: span {s.span_id}, {s.bytes} B, step {s.created_step}. "
                "Ask to retrieve it if needed.]"
            )
            stubs.append(
                NewSpan(
                    span_id=f"stub-{s.span_id}",
                    bytes=len(content.encode("utf-8")),
                    summary_of=(s.span_id,),
                    content=content,
                    span_class="tool_stub",
                )
            )
        dropped = tuple(
            drop_record(s, "subagent_isolation archived")
            for s in window.spans
            if s.span_id in dropped_ids
        )
        return WindowDiff(
            op=self.name,
            kept_spans=tuple(s.span_id for s in window.spans if s.span_id not in dropped_ids),
            dropped_spans=dropped,
            new_spans=tuple(stubs),
            cache_head_unchanged=True,
        )
