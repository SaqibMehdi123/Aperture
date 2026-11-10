"""Curation Engine: compose the next context window by executing an operator
plan under guardrails (spec 7.1, "Curation Engine"; 7.2 steps 2-4).

The engine is the only component allowed to mutate a window. It applies the
plan in `order`, runs the guardrail on every diff (destructive operators
cannot drop pinned/protected spans - AG2), and records every diff for the
trace ledger.
"""

from __future__ import annotations

from collections.abc import Iterable

from aperture.interfaces import PlannedOp
from aperture.session import (
    SPAN_SUMMARY,
    Features,
    NewSpan,
    Span,
    Window,
    WindowDiff,
)


def enforce_guardrail(window: Window, diff: WindowDiff) -> WindowDiff:
    """Veto drops of pinned or protected spans (spec 7.2 step 2).

    The guardrail is a property of the engine, not of individual operators:
    even a buggy or adversarial operator cannot silently destroy protected
    content. Vetoed drops are removed from the diff; surviving (retained)
    spans keep the window safe.
    """
    vetoed: set[str] = set()
    for dropped in diff.dropped_spans:
        span = window.find(dropped.span_id)
        if span is not None and (span.pinned or span.protected):
            vetoed.add(dropped.span_id)
    if not vetoed:
        return diff
    kept_drops = tuple(d for d in diff.dropped_spans if d.span_id not in vetoed)
    probe_targets = tuple(
        t for t in diff.probe_targets if t not in vetoed
    ) + tuple(vetoed)  # vetoed spans become probe targets: prove they survived
    return WindowDiff(
        op=diff.op,
        kept_spans=diff.kept_spans,
        dropped_spans=kept_drops,
        new_spans=diff.new_spans,
        cache_head_unchanged=diff.cache_head_unchanged,
        probe_targets=probe_targets,
    )


def apply_diff(window: Window, diff: WindowDiff) -> Window:
    """Return the successor window: drop the diff's spans, add its new spans."""
    dropped_ids = {d.span_id for d in diff.dropped_spans}
    spans = [s for s in window.spans if s.span_id not in dropped_ids]
    for new in diff.new_spans:
        if not new.content:
            continue
        spans.append(
            Span(
                span_id=new.span_id,
                span_class=SPAN_SUMMARY,
                content=new.content,
                created_step=window.step,
                summary_of=new.summary_of,
            )
        )
    return Window(token_budget=window.token_budget, spans=spans, step=window.step)


class CurationEngine:
    """Executes operator plans; owns the guardrail (spec 7.1)."""

    def __init__(self, registry: dict[str, object] | None = None) -> None:
        # registry maps op name -> Operator; imported lazily to avoid cycles.
        if registry is None:
            from aperture import operators as ops_module

            registry = ops_module.registry()
        self._registry = registry

    def compose(
        self,
        window: Window,
        plan: Iterable[PlannedOp],
        ctx: Features,
    ) -> tuple[Window, list[WindowDiff]]:
        """Apply the plan in order; return (successor window, diffs in order)."""
        current = window.clone()
        diffs: list[WindowDiff] = []
        for planned in sorted(plan, key=lambda p: p.order):
            if planned.op not in self._registry:
                raise KeyError(f"unknown operator: {planned.op!r}")
            op = self._registry[planned.op]
            before_head = current.head_fingerprint()
            diff = op.apply(current, ctx, dict(planned.params))
            diff = enforce_guardrail(current, diff)
            current = apply_diff(current, diff)
            after_head = current.head_fingerprint()
            if diff.cache_head_unchanged and before_head != after_head:
                # Operators claim cache-head effects honestly; the engine verifies.
                diff = WindowDiff(
                    op=diff.op,
                    kept_spans=diff.kept_spans,
                    dropped_spans=diff.dropped_spans,
                    new_spans=diff.new_spans,
                    cache_head_unchanged=False,
                    probe_targets=diff.probe_targets,
                )
            diffs.append(diff)
        return current, diffs


def new_span_from_summary(
    span_id: str, content: str, summary_of: Iterable[str]
) -> NewSpan:
    return NewSpan(
        span_id=span_id,
        bytes=len(content.encode("utf-8")),
        summary_of=tuple(summary_of),
        content=content,
    )
