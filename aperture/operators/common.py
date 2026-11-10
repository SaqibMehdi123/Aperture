"""Shared operator helpers."""

from __future__ import annotations

from aperture.session import DroppedSpan, Span


def drop_record(span: Span, reason: str) -> DroppedSpan:
    """The audit record for one dropped span (Appendix A `diffs[].dropped[]`)."""
    return DroppedSpan(
        span_id=span.span_id,
        reason=reason,
        bytes=span.bytes,
        classes=(span.span_class,),
    )


def droppable(window, include_head: bool = False):
    """Spans an operator may drop: not the cache head, not pinned/protected."""
    return [
        s
        for s in window.spans
        if (include_head or not s.cache_head) and not (s.pinned or s.protected)
    ]
