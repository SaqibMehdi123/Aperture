"""Trace ledger, survival probes, and the replay engine (spec 7.4 trace/)."""

from aperture.engine import CurationEngine
from aperture.interfaces import PlannedOp
from aperture.session import Features, Span, Window
from aperture.trace.ledger import TraceLedger
from aperture.trace.probes import ProbeSpec, run_survival_probes
from aperture.trace.replay import (
    diff_signature,
    plan_from_record,
    replay_step,
    window_diff_to_record,
)
from bench.schema import EXAMPLE_V1, TraceRecord


def make_window():
    head = Span(span_id="sys", span_class="system", content="system prompt", cache_head=True)
    tools = [
        Span(span_id=f"t{i}", span_class="tool_result", content=f"output {i} " + "x" * 40)
        for i in range(6)
    ]
    return Window(token_budget=10**6, spans=[head, *tools])


def _features(w):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )


def make_record(window, diffs, step=3):
    return TraceRecord(
        **{
            "schema": "curatebench/trace@v1",
            "step": step,
            "ts": "2027-03-14T09:22:11.408Z",
            "session_id": "s-1",
            "arm": "aperture_fixed",
            "model": {"provider": "synthetic", "id": "synthetic-1", "price_list": "synthetic"},
            "features": {
                "budget_used_frac": 0.5,
                "task_phase": "act",
                "tool_output_tokens_recent": 10,
                "redundancy_score": 0.0,
                "drift_score": 0.0,
                "prefix_hash": window.prefix_hash(),
            },
            "plan": [{"op": "keep_recent", "params": {"keep_n": 2}, "order": 0}],
            "diffs": [window_diff_to_record(d).model_dump() for d in diffs],
            "cache": {
                "prefix_tokens": 4,
                "hit": False,
                "invalidated_bytes": 0,
                "discount_usd": 0.0,
            },
            "probes": [],
            "call": {"input_tokens": 100, "output_tokens": 4, "cost_usd": 0.001, "latency_ms": 2.0},
            "reward": {
                "task_progress": 0.0,
                "cost_delta_usd": 0.001,
                "survival_penalty": 0.0,
                "latency_ms": 2.0,
            },
        }
    )


def _compose_keep(w, keep_n=2):
    engine = CurationEngine()
    _, diffs = engine.compose(
        w, [PlannedOp(op="keep_recent", params={"keep_n": keep_n}, order=0)], _features(w)
    )
    return diffs


def test_ledger_append_and_read(tmp_path):
    ledger = TraceLedger(tmp_path / "trace.jsonl")
    w = make_window()
    diffs = _compose_keep(w)
    ledger.record(make_record(w, diffs, step=0))
    ledger.record(make_record(w, diffs, step=1))
    assert len(ledger) == 2
    steps = [r.step for r in ledger.records()]
    assert steps == [0, 1]  # append order preserved


def test_ledger_rejects_non_schema_lines(tmp_path):
    ledger = TraceLedger(tmp_path / "trace.jsonl")
    ledger.path.write_text(
        '{"schema": "curatebench/trace@v1"}\nnot json at all\n', encoding="utf-8"
    )
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        list(ledger.records())


def test_outcome_sidecar_join(tmp_path):
    ledger = TraceLedger(tmp_path / "trace.jsonl")
    w = make_window()
    diffs = _compose_keep(w)
    ledger.record(make_record(w, diffs, step=0))
    ledger.write_outcome("s-1", 0, success=True, graded_at="2027-03-14T09:31:02Z")
    joined = list(ledger.join_outcomes())
    assert joined[0].outcome.task_success is True
    assert joined[0].outcome.graded_at.endswith("Z")


def test_survival_probes_containment():
    w = make_window()
    w.spans.append(
        Span(span_id="c0", span_class="constraint", content="Refunds are approved only if...")
    )
    specs = [
        ProbeSpec(
            probe_id="refund-policy",
            span_class="constraint",
            pattern="Refunds are approved only if",
        ),
        ProbeSpec(probe_id="missing", span_class="constraint", pattern="NOT IN CONTEXT"),
        ProbeSpec(
            probe_id="wrong-class",
            span_class="system",
            pattern="Refunds are approved only if",
        ),
    ]
    outcomes = run_survival_probes(w, specs)
    assert [o.survived for o in outcomes] == [True, False, False]


def test_replay_reproduces_recorded_step_bit_identically():
    """G2 groundwork: same plan on the reconstructed window -> same diffs."""
    w = make_window()
    engine = CurationEngine()
    plan = [PlannedOp(op="keep_recent", params={"keep_n": 2}, order=0)]
    _, diffs = engine.compose(w, plan, _features(w))
    record = make_record(w, diffs)

    result = replay_step(record, w.clone(), engine)
    assert diff_signature(list(result.trace_diffs)) == diff_signature(
        [window_diff_to_record(d) for d in diffs]
    )
    assert [d.op for d in result.diffs] == [d.op for d in diffs]
    # Deterministic content -> byte counts match exactly.
    recorded_bytes = sorted(d.bytes for diff in diffs for d in diff.dropped_spans)
    replayed_bytes = sorted(d.bytes for diff in result.diffs for d in diff.dropped_spans)
    assert recorded_bytes == replayed_bytes


def test_replay_counterfactual_differs():
    w = make_window()
    engine = CurationEngine()
    plan = [PlannedOp(op="keep_recent", params={"keep_n": 2}, order=0)]
    _, diffs = engine.compose(w, plan, _features(w))
    record = make_record(w, diffs)

    alt = [PlannedOp(op="keep_recent", params={"keep_n": 5}, order=0)]
    result = replay_step(record, w.clone(), engine, plan=alt)
    assert diff_signature(list(result.trace_diffs)) != diff_signature(
        [window_diff_to_record(d) for d in diffs]
    )
    assert result.total_tokens > _tokens_after(w, diffs)  # gentler plan keeps more


def test_plan_from_record_sorts_by_order():
    record = TraceRecord.model_validate(EXAMPLE_V1)
    ops = plan_from_record(record)
    assert [o.order for o in ops] == sorted(o.order for o in ops)
    assert ops[0].op == "cache_align"


def _tokens_after(w, diffs):
    dropped = {d.span_id for diff in diffs for d in diff.dropped_spans}
    return sum(s.tokens for s in w.spans if s.span_id not in dropped)
