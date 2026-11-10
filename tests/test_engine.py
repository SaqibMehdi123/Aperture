"""Curation Engine: ordered composition + the guardrail (spec 7.2 step 2)."""

import pytest
from aperture.engine import CurationEngine, apply_diff, enforce_guardrail
from aperture.interfaces import PlannedOp
from aperture.session import Features, Span, Window


class PinBlindTruncate:
    """Adversarial operator: drops everything except the last N spans."""

    name = "pin_blind_truncate"

    def cost_hint(self, window, params):
        return 1

    def apply(self, window, ctx, params):
        from aperture.session import DroppedSpan, WindowDiff

        keep_n = max(1, int(params.get("keep_n", 1)))
        keep = {s.span_id for s in window.spans[-keep_n:]}
        dropped = tuple(
            DroppedSpan(span_id=s.span_id, reason="blind", bytes=s.bytes, classes=(s.span_class,))
            for s in window.spans
            if s.span_id not in keep
        )
        return WindowDiff(op=self.name, dropped_spans=dropped, cache_head_unchanged=False)


def make_window():
    head = Span(span_id="sys", span_class="system", content="system", cache_head=True, pinned=True)
    constraint = Span(
        span_id="c0",
        span_class="constraint",
        content="policy text",
        pinned=True,
        protected=True,
        cache_head=True,
    )
    tools = [Span(span_id=f"t{i}", span_class="tool_result", content=f"tool {i}") for i in range(4)]
    return Window(token_budget=10**6, spans=[head, constraint, *tools])


def _features(w):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )


def test_guardrail_vetoes_protected_drops():
    w = make_window()
    op = PinBlindTruncate()
    raw = op.apply(w, _features(w), {"keep_n": 1})
    assert "c0" in {d.span_id for d in raw.dropped_spans}  # the operator tries
    safe = enforce_guardrail(w, raw)
    assert "c0" not in {d.span_id for d in safe.dropped_spans}
    assert "c0" in safe.probe_targets  # vetoed spans become probe targets


def test_engine_compose_protects_pinned_spans_even_from_adversarial_ops():
    w = make_window()
    engine = CurationEngine(registry={"pin_blind_truncate": PinBlindTruncate()})
    composed, diffs = engine.compose(
        w, [PlannedOp(op="pin_blind_truncate", params={"keep_n": 1}, order=0)], _features(w)
    )
    ids = {s.span_id for s in composed.spans}
    assert "sys" in ids and "c0" in ids  # pinned + protected survive


def test_engine_verifies_cache_head_claims():
    w = make_window()
    # Remove pinning from the head so the blind op may legally drop it.
    w.spans[0] = Span(span_id="sys", span_class="system", content="system", cache_head=False)
    op = PinBlindTruncate()  # claims cache_head_unchanged=False -> engine keeps it False
    engine = CurationEngine(registry={"pin_blind_truncate": op})
    composed, diffs = engine.compose(
        w, [PlannedOp(op="pin_blind_truncate", params={"keep_n": 3}, order=0)], _features(w)
    )
    assert diffs[0].cache_head_unchanged is False  # head really changed


def test_engine_applies_plan_in_order():
    from aperture.operators.keep_recent import KeepRecent

    w = make_window()
    engine = CurationEngine(registry={"keep_recent": KeepRecent()})
    plan = [
        PlannedOp(op="keep_recent", params={"keep_n": 5}, order=0),
        PlannedOp(op="keep_recent", params={"keep_n": 2}, order=1),
    ]
    composed, diffs = engine.compose(w, plan, _features(w))
    assert [d.op for d in diffs] == ["keep_recent", "keep_recent"]
    # First (order 0, keep 5 of 4 droppable) is a no-op; second (order 1, keep 2) drops.
    assert len(diffs[0].dropped_spans) == 0
    assert len(diffs[1].dropped_spans) > 0
    assert composed.total_tokens() < w.total_tokens()


def test_unknown_operator_raises():
    engine = CurationEngine(registry={})
    with pytest.raises(KeyError):
        engine.compose(make_window(), [PlannedOp(op="ghost")], _features(make_window()))


def test_apply_diff_adds_summary_spans():
    from aperture.session import NewSpan, WindowDiff

    w = make_window()
    diff = WindowDiff(
        op="summarize",
        dropped_spans=(),
        new_spans=(
            NewSpan(span_id="sum1", bytes=10, summary_of=("t0", "t1"), content="a summary"),
        ),
    )
    w2 = apply_diff(w, diff)
    assert any(s.span_id == "sum1" and s.span_class == "summary" for s in w2.spans)
    assert w2.find("sum1").summary_of == ("t0", "t1")
