"""summarize: fold the oldest droppable spans into one compact summary span.

The default summarizer is extractive and dependency-free (first sentence per
span, bounded); a project can inject any callable - an LLM call, a local
model - via `Summarize(summarizer=fn)`. The folded spans are dropped with
provenance (`summary_of`), so the trace and the archive keep the full story.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.operators.common import drop_record, droppable
from aperture.session import Features, NewSpan, Window, WindowDiff

SummarizerFn = Callable[[list[str]], str]


def _first_sentence(text: str, cap: int) -> str:
    text = " ".join(text.split())
    for i, ch in enumerate(text):
        if ch in ".!?" and (i + 1 == len(text) or text[i + 1] == " "):
            return text[: i + 1][:cap]
    return text[:cap]


def extractive_summarizer(contents: list[str], per_span_chars: int = 160) -> str:
    """Bounded extractive default: first sentence of each span, one per line."""
    lines = [_first_sentence(c, per_span_chars) for c in contents]
    return "\n".join(line for line in lines if line)


@register
class Summarize:
    name = "summarize"

    def __init__(self, summarizer: SummarizerFn | None = None) -> None:
        self._summarizer = summarizer

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        # Extraction is linear in the folded volume; scale work units by size.
        return len(window.spans) * 2

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        max_spans = int(params.get("max_spans", 8))
        per_span_chars = int(params.get("per_span_chars", 160))
        candidates = droppable(window)[:max_spans]
        if not candidates:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        contents = [s.content for s in candidates]
        if self._summarizer is not None:
            summary = self._summarizer(contents)
        else:
            summary = extractive_summarizer(contents, per_span_chars)
        summary_of = tuple(s.span_id for s in candidates)
        new_id = (
            f"sum-{window.step}-{hashlib.sha256(','.join(summary_of).encode()).hexdigest()[:8]}"
        )
        dropped_ids = {s.span_id for s in candidates}

        return WindowDiff(
            op=self.name,
            kept_spans=tuple(s.span_id for s in window.spans if s.span_id not in dropped_ids),
            dropped_spans=tuple(drop_record(s, "summarize folded") for s in candidates),
            new_spans=(
                NewSpan(
                    span_id=new_id,
                    bytes=len(summary.encode("utf-8")),
                    summary_of=summary_of,
                    content=summary,
                ),
            ),
            cache_head_unchanged=True,
        )
