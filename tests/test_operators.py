"""Operator registry and keep_recent semantics (spec 7.1, 7.3)."""

import pytest
from aperture.operators import available, get, registry
from aperture.operators.keep_recent import KeepRecent
from aperture.session import Span, Window


def make_window():
    head = Span(span_id="sys", span_class="system", content="system", cache_head=True)
    old = [Span(span_id=f"o{i}", span_class="tool_result", content=f"old {i}") for i in range(5)]
    recent = [
        Span(span_id=f"r{i}", span_class="tool_result", content=f"recent {i}") for i in range(3)
    ]
    pinned = Span(span_id="p1", span_class="conversation", content="pin me", pinned=True)
    return Window(token_budget=10**6, spans=[head, *old, pinned, *recent])


def test_registry_contains_keep_recent():
    assert "keep_recent" in registry()
    assert "keep_recent" in available()
    assert isinstance(get("keep_recent"), KeepRecent)
    with pytest.raises(KeyError):
        get("does_not_exist")


def test_keep_recent_drops_oldest_beyond_n():
    w = make_window()
    diff = get("keep_recent").apply(w, _features(w), {"keep_n": 3})
    dropped_ids = {d.span_id for d in diff.dropped_spans}
    # droppable tail = o0..o4, r0..r2 (8); keep 3 -> drop oldest 5
    assert dropped_ids == {"o0", "o1", "o2", "o3", "o4"}
    assert diff.cache_head_unchanged is True


def test_keep_recent_never_drops_head_or_pinned():
    w = make_window()
    diff = get("keep_recent").apply(w, _features(w), {"keep_n": 0})
    dropped_ids = {d.span_id for d in diff.dropped_spans}
    assert "sys" not in dropped_ids  # cache head untouched
    assert "p1" not in dropped_ids  # pinned survives even at keep_n=0


def test_keep_recent_noop_when_room():
    w = make_window()
    diff = get("keep_recent").apply(w, _features(w), {"keep_n": 100})
    assert diff.dropped_spans == ()
    assert set(diff.kept_spans) == {s.span_id for s in w.spans}


def test_keep_recent_constraint_drops_become_probe_targets():
    w = make_window()
    w.spans.insert(1, Span(span_id="c0", span_class="constraint", content="policy"))
    diff = get("keep_recent").apply(w, _features(w), {"keep_n": 3})
    assert "c0" in diff.probe_targets


def test_cost_hint_is_cheap():
    w = make_window()
    op = get("keep_recent")
    assert op.cost_hint(w, {}) == len(w.spans)


def _features(w):
    from aperture.session import Features

    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )
