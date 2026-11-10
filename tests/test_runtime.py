"""Runtime facade: toy loop wrapped end to end (P0 weeks 1-2 exit criterion)."""

import aperture
from aperture.models.gateway import SyntheticGateway
from aperture.trace.ledger import TraceLedger


def run_toy(tmp_path, token_budget=2000, n_tools=30):
    ledger = TraceLedger(tmp_path / "trace.jsonl")
    rt = aperture.Aperture(model=SyntheticGateway(), ledger=ledger)

    def loop(session):
        session.add_span(
            "You are a terse research assistant.",
            span_class="system",
            cache_head=True,
            pinned=True,
            protected=True,
        )
        session.register_probe("system-prompt-intact", "system", "terse research assistant")
        for i in range(n_tools):
            session.add_span(f"tool output {i}: {'lorem ipsum ' * 30}", span_class="tool_result")
        session.arm = "aperture_fixed"
        first = session.complete()
        second = session.complete()
        session.finish(success=True)
        return first, second

    results = rt.wrap(loop, session_id="toy-001", token_budget=token_budget)
    return rt, ledger, results


def test_toy_loop_writes_valid_versioned_trace(tmp_path):
    _, ledger, (first, _) = run_toy(tmp_path)
    records = list(ledger.records())
    assert len(records) == 2
    rec = records[0]
    assert rec.schema_ == "curatebench/trace@v1"
    assert rec.arm == "aperture_fixed"
    assert rec.session_id == "toy-001"
    assert rec.call.input_tokens > 0
    assert rec.call.cost_usd > 0
    assert first.text == "ok"


def test_heuristic_triggers_keep_recent_under_budget_pressure(tmp_path):
    _, ledger, _ = run_toy(tmp_path, token_budget=2000)
    rec = list(ledger.records())[0]
    assert [p.op for p in rec.plan] == ["keep_recent"]
    assert sum(len(d.dropped) for d in rec.diffs) > 0  # old tool outputs dropped


def test_guardrail_keeps_protected_head(tmp_path):
    _, ledger, _ = run_toy(tmp_path, token_budget=2000)
    rec = list(ledger.records())[0]
    assert all(p.survived for p in rec.probes)  # system prompt probe passes
    assert rec.reward.survival_penalty == 0.0


def test_cache_hit_on_unchanged_head(tmp_path):
    _, ledger, _ = run_toy(tmp_path, token_budget=2000)
    rec1, rec2 = list(ledger.records())
    assert rec1.cache.hit is False  # first call: cold cache
    assert rec2.cache.hit is True  # head untouched by keep_recent -> warm
    assert rec2.cache.discount_usd > 0
    assert rec1.cache.discount_usd == 0.0


def test_outcome_join(tmp_path):
    _, ledger, _ = run_toy(tmp_path)
    joined = list(ledger.join_outcomes())
    assert all(r.outcome is not None and r.outcome.task_success for r in joined)


def test_features_are_populated(tmp_path):
    _, ledger, _ = run_toy(tmp_path, token_budget=2000)
    rec = list(ledger.records())[0]
    f = rec.features
    assert 0.0 < f.budget_used_frac <= 1.0
    assert f.tool_output_tokens_recent > 0
    assert len(f.prefix_hash) == 16
    assert f.task_phase == "explore"


def test_wrap_module_level_entry(tmp_path):
    ledger = TraceLedger(tmp_path / "t.jsonl")

    def loop(session):
        session.add_span("hi", span_class="system", cache_head=True)
        return session.complete().text

    out = aperture.wrap(loop, model=SyntheticGateway(), ledger=ledger, session_id="w-1")
    assert out == "ok"
    assert len(ledger) == 1
