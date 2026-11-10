"""P1 operators: pin_protected + cache_align (spec Table 6 P1; AG1/AG2 groundwork).

pin_protected marks constraint-like content pinned+protected via class rules and
regex heuristics - annotations, not drops. cache_align makes the cache-stable
prefix explicit. Both use the WindowDiff `pinned[]` annotation channel added in
trace schema v2, so every flag change is logged and replayable.
"""

from aperture.engine import CurationEngine, apply_diff
from aperture.interfaces import PlannedOp
from aperture.operators import available, get
from aperture.operators.cache_align import CacheAlign
from aperture.operators.pin_protected import PinProtected
from aperture.session import Features, Span, Window
from bench.schema import EXAMPLE_V1, SCHEMA_VERSIONED, DiffRecord, TraceRecord


def make_window():
    return Window(
        token_budget=32768,
        spans=[
            # system prompt present but NOT yet flagged as cache head:
            # cache_align's job is to make the stable prefix explicit.
            Span(span_id="sys", span_class="system", content="system prompt"),
            Span(span_id="u0", span_class="conversation", content="quick question about invoices"),
            Span(span_id="t0", span_class="tool_result", content="Regular tool output number one"),
            Span(
                span_id="t1",
                span_class="tool_result",
                content="POLICY: you must never approve refunds above 500 USD without escalation",
            ),
            Span(span_id="t2", span_class="tool_result", content="Regular tool output number two"),
        ],
        step=3,
    )


def _features(w):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )


# -------------------------------------------------------- pin_protected ---
def test_pin_protected_registered():
    assert "pin_protected" in available()
    assert get("pin_protected").name == "pin_protected"


def test_class_constraint_is_always_pinned():
    w = make_window()
    w.spans.append(Span(span_id="c9", span_class="constraint", content="short rule"))
    diff = PinProtected().apply(w, _features(w), {})
    by_id = {p.span_id: p for p in diff.pinned}
    assert by_id["c9"].pinned and by_id["c9"].protected


def test_heuristic_patterns_flag_constraint_like_text():
    w = make_window()
    diff = PinProtected().apply(w, _features(w), {})
    by_id = {p.span_id: p for p in diff.pinned}
    assert "t1" in by_id  # "POLICY:" + "must never" heuristics
    assert by_id["t1"].pinned and by_id["t1"].protected
    assert "t0" not in by_id and "u0" not in by_id  # benign spans untouched


def test_extra_patterns_param():
    w = make_window()
    diff = PinProtected().apply(w, _features(w), {"extra_patterns": ["invoices"]})
    by_id = {p.span_id: p for p in diff.pinned}
    assert "u0" in by_id


def test_pin_protected_drops_nothing():
    w = make_window()
    diff = PinProtected().apply(w, _features(w), {})
    assert len(diff.dropped_spans) == 0 and len(diff.new_spans) == 0
    assert diff.cache_head_unchanged is True


def test_already_pinned_spans_not_annotated_again():
    from aperture.engine import apply_diff

    w = make_window()
    w2 = apply_diff(w, PinProtected().apply(w, _features(w), {}))  # flags applied
    diff2 = PinProtected().apply(w2, _features(w2), {})
    assert len(diff2.pinned) == 0  # idempotent


def test_engine_applies_pin_annotations():
    engine = CurationEngine(registry={"pin_protected": PinProtected()})
    w = make_window()
    composed, diffs = engine.compose(w, [PlannedOp(op="pin_protected", order=0)], _features(w))
    t1 = composed.find("t1")
    assert t1.pinned and t1.protected
    # annotations survive the trace round-trip (schema v2)
    from aperture.trace.replay import window_diff_to_record

    rec = window_diff_to_record(diffs[0])
    assert any(p.span_id == "t1" and p.pinned for p in rec.pinned)


def test_annotation_protects_against_later_drops():
    # A span pinned by pin_protected must survive a subsequent destructive op.
    from aperture.operators.keep_recent import KeepRecent

    engine = CurationEngine(registry={"pin_protected": PinProtected(), "keep_recent": KeepRecent()})
    w = make_window()
    plan = [
        PlannedOp(op="pin_protected", order=0),
        PlannedOp(op="keep_recent", params={"keep_n": 1}, order=1),
    ]
    composed, _ = engine.compose(w, plan, _features(w))
    assert composed.find("t1") is not None  # flagged span survived keep_recent


# ------------------------------------------------------------ cache_align ---
def test_cache_align_registered():
    assert "cache_align" in available()
    assert get("cache_align").name == "cache_align"


def test_cache_align_promotes_stable_prefix():
    w = make_window()
    diff = CacheAlign(head_budget=512).apply(w, _features(w), {})
    by_id = {p.span_id: p for p in diff.pinned}
    assert by_id["sys"].cache_head is True  # system span promoted into the head
    # u0 is conversation -> the headable run stops before it
    assert "u0" not in by_id and "t0" not in by_id


def test_cache_align_noop_when_aligned():
    w = make_window()
    w.spans[0] = Span(
        span_id="sys", span_class="system", content="system prompt", cache_head=True, pinned=True
    )
    diff = CacheAlign(head_budget=512).apply(w, _features(w), {})
    assert len(diff.pinned) == 0
    assert diff.cache_head_unchanged is True


def test_cache_align_honest_head_change_flag():
    # sys is NOT head yet; aligning promotes it -> head composition changes.
    w = make_window()
    diff = CacheAlign(head_budget=512).apply(w, _features(w), {})
    assert diff.cache_head_unchanged is False
    w2 = apply_diff(w, diff)
    assert w2.head_spans()[0].span_id == "sys"


def test_cache_align_respects_head_budget():
    big = Span(span_id="sys-big", span_class="system", content="x" * 4000, cache_head=False)
    w = Window(
        token_budget=10**6, spans=[big, Span(span_id="t0", span_class="tool_result", content="y")]
    )
    diff = CacheAlign(head_budget=100).apply(w, _features(w), {})
    assert len(diff.pinned) == 0  # span exceeds the head budget: left alone


def test_engine_verifies_align_claim():
    engine = CurationEngine(registry={"cache_align": CacheAlign(head_budget=512)})
    w = make_window()
    composed, diffs = engine.compose(w, [PlannedOp(op="cache_align", order=0)], _features(w))
    assert diffs[0].cache_head_unchanged is False  # head really changed


# ---------------------------------------------------------- schema v2 ---
def test_schema_bumped_to_v2_additively():
    assert SCHEMA_VERSIONED == "curatebench/trace@v2"
    rec = TraceRecord.model_validate(EXAMPLE_V1)  # v1 records still parse
    assert rec.diffs[0].pinned == []


def test_diff_record_pinned_roundtrip():
    d = DiffRecord(
        op="pin_protected",
        pinned=[{"span_id": "t1", "pinned": True, "protected": True, "cache_head": False}],
    )
    again = DiffRecord.model_validate_json(d.model_dump_json())
    assert again.pinned[0].span_id == "t1" and again.pinned[0].protected
