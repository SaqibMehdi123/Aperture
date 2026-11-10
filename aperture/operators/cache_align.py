"""cache_align: make the cache-stable prefix explicit (AG1 groundwork).

Provider prompt caches bill a stable prefix at a steep discount, so the
window should carry an explicit, contiguous, stable head: system prompt,
constraints, pinned context. cache_align walks the window from the start and
flags the leading run of headable spans (system/constraint/pinned/protected)
up to `head_budget` tokens. It never drops anything; when it changes head
composition it reports `cache_head_unchanged=False` honestly (the next call
pays one cache write; every later call hits).
"""

from __future__ import annotations

from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.session import Features, PinUpdate, Window, WindowDiff

HEADABLE_CLASSES = ("system", "constraint")


@register
class CacheAlign:
    name = "cache_align"

    def __init__(self, head_budget: int = 2048) -> None:
        self.head_budget = head_budget

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return 1

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        budget = int(params.get("head_budget", self.head_budget))
        annotations: list[PinUpdate] = []
        used = 0
        changed = False
        for span in window.spans:
            headable = span.span_class in HEADABLE_CLASSES or span.pinned or span.protected
            if not headable:
                break  # the head is a contiguous prefix; stop at the first tail span
            if span.cache_head:
                used += span.tokens
                continue  # already part of the head
            if used + span.tokens > budget:
                break
            annotations.append(PinUpdate(span_id=span.span_id, cache_head=True))
            used += span.tokens
            changed = True

        return WindowDiff(
            op=self.name,
            kept_spans=tuple(s.span_id for s in window.spans),
            cache_head_unchanged=not changed,
            pinned=tuple(annotations),
        )
