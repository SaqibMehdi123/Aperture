"""Protected-class metadata (AG2 groundwork, P1): the guardrail protects whole
span CLASSES, not only explicitly flagged spans. A constraint span must survive
curation even if an adapter forgets to set `protected=True`.
"""

from aperture.engine import CurationEngine, enforce_guardrail
from aperture.interfaces import PlannedOp
from aperture.protection import ProtectedClasses
from aperture.session import DroppedSpan, Features, Span, Window, WindowDiff


class DropAll:
    name = "drop_all"

    def cost_hint(self, window, params):
        return 1

    def apply(self, window, ctx, params):
        dropped = tuple(
            DroppedSpan(
                span_id=s.span_id, reason="drop-all", bytes=s.bytes, classes=(s.span_class,)
            )
            for s in window.spans
        )
        return WindowDiff(op=self.name, dropped_spans=dropped, cache_head_unchanged=False)


def make_window():
    spans = [
        Span(span_id="sys", span_class="system", content="sys"),
        # class "constraint" WITHOUT flags: protection must come from the class registry
        Span(span_id="c0", span_class="constraint", content="never expose secrets"),
        Span(span_id="t0", span_class="tool_result", content="tool"),
    ]
    return Window(token_budget=10**6, spans=spans)


def _features(w):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )


def test_default_registry_protects_constraint_class():
    pc = ProtectedClasses()
    assert pc.is_protected("constraint")
    assert not pc.is_protected("tool_result")


def test_guardrail_vetoes_protected_class_without_flags():
    w = make_window()
    raw = DropAll().apply(w, _features(w), {})
    assert "c0" in {d.span_id for d in raw.dropped_spans}  # the operator tries
    safe = enforce_guardrail(w, raw)
    assert "c0" not in {d.span_id for d in safe.dropped_spans}  # vetoed by class
    assert "c0" in safe.probe_targets  # vetoed spans become probe targets
    assert "t0" in {d.span_id for d in safe.dropped_spans}  # unprotected span still drops


def test_engine_protects_constraint_class_end_to_end():
    engine = CurationEngine(registry={"drop_all": DropAll()})
    composed, diffs = engine.compose(
        make_window(), [PlannedOp(op="drop_all", order=0)], _features(make_window())
    )
    ids = {s.span_id for s in composed.spans}
    assert "c0" in ids  # class-level protection held


def test_engine_custom_protected_classes():
    pc = ProtectedClasses()
    pc.register("audit_log")  # a project-specific protected class
    engine = CurationEngine(registry={"drop_all": DropAll()}, protected_classes=pc)
    w = Window(
        token_budget=10**6,
        spans=[
            Span(span_id="a0", span_class="audit_log", content="audit trail"),
            Span(span_id="t0", span_class="tool_result", content="x"),
        ],
    )
    composed, _ = engine.compose(w, [PlannedOp(op="drop_all", order=0)], _features(w))
    assert any(s.span_id == "a0" for s in composed.spans)


def test_registry_can_unprotect():
    pc = ProtectedClasses()
    pc.unregister("constraint")
    assert not pc.is_protected("constraint")
