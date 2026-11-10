"""semantic_retrieval: pull archived content back into the window on demand.

Reads the per-session ArchiveView the runtime injects via `Features.archive`
and re-admits the most relevant archived spans as compact "retrieved" spans
with provenance. Non-destructive. The default scorer is lexical (Jaccard over
word tokens, dependency-free and deterministic); a pluggable embedder can
replace it in P4 without touching call sites.
"""

from __future__ import annotations

from typing import Any

from aperture.interfaces import Operator  # noqa: F401 - protocol documentation
from aperture.operators import register
from aperture.session import Features, NewSpan, Window, WindowDiff

RETRIEVED_CLASS = "retrieved"


@register
class SemanticRetrieval:
    name = "semantic_retrieval"

    def cost_hint(self, window: Window, params: dict[str, Any]) -> int:
        return 3  # lexical scoring over the session archive is cheap

    def apply(self, window: Window, ctx: Features, params: dict[str, Any]) -> WindowDiff:
        archive = ctx.archive
        if archive is None:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        query = str(params.get("query", "")) or _default_query(window)
        top_k = int(params.get("top_k", 2))
        min_score = float(params.get("min_score", 0.05))
        max_chars = int(params.get("max_chars", 1200))
        if not query:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        live_ids = {s.span_id for s in window.spans}
        hits = [
            h
            for h in archive.search(query, top_k=top_k * 2, min_score=min_score)
            if h.span_id not in live_ids
        ][:top_k]
        if not hits:
            return WindowDiff(
                op=self.name,
                kept_spans=tuple(s.span_id for s in window.spans),
                cache_head_unchanged=True,
            )

        new_spans = []
        for h in hits:
            body = h.content[:max_chars]
            content = f"[retrieved:{h.span_id}] {body}"
            new_spans.append(
                NewSpan(
                    span_id=f"ret-{h.span_id}",
                    bytes=len(content.encode("utf-8")),
                    summary_of=(h.span_id,),
                    content=content,
                    span_class=RETRIEVED_CLASS,
                )
            )
        return WindowDiff(
            op=self.name,
            kept_spans=tuple(s.span_id for s in window.spans),
            new_spans=tuple(new_spans),
            cache_head_unchanged=True,
        )


def _default_query(window: Window) -> str:
    """The most recent conversation/assistant turn is the implicit query."""
    for span in reversed(window.spans):
        if span.span_class in ("conversation", "assistant"):
            return span.content
    return ""
