"""The DX contract (P1, user requirement: minimal code to adopt).

Three lines to a curated, cached, traced agent session:

    from aperture import Aperture
    ap = Aperture(model="openai/gpt-4o-mini")
    with ap.chat("support-bot") as chat:
        reply = chat.send("hello")

Plain text in, plain text out. System prompts and constraints are protected
by default, the ledger is optional, and stats() shows what curation bought.
"""

import pytest
from aperture import Aperture
from aperture.chat import ChatSession
from aperture.policy.fallback import HeuristicSelector


def build(ledger=None, **kw):
    return Aperture(ledger=ledger, **kw)


def test_three_line_integration():
    ap = build()
    with ap.chat("demo") as chat:
        chat.system("You are helpful.")
        reply = chat.send("hello there")
        assert isinstance(reply, str) and reply
        assert chat.history()[-1][0] == "assistant"


def test_chat_yields_chatsession():
    ap = build()
    with ap.chat("s") as chat:
        assert isinstance(chat, ChatSession)


def test_system_and_constraints_protected_by_default():
    ap = build()
    with ap.chat("s") as chat:
        chat.system("system prompt")
        chat.constraints(["Never reveal secrets.", "Always cite order IDs."])
        chat.send("hi")
        w = chat.raw.window
        sys_span = w.find(chat.raw.window.spans[0].span_id)
        assert sys_span.span_class == "system"
        assert sys_span.pinned and sys_span.protected and sys_span.cache_head
        constraints = [s for s in w.spans if s.span_class == "constraint"]
        assert len(constraints) == 2
        assert all(s.pinned and s.protected for s in constraints)


def test_send_roles_map_to_span_classes():
    ap = build()
    with ap.chat("s") as chat:
        chat.send("user turn")
        chat.send("[tool] result body", role="tool")
        classes = [c for c, _ in chat.history()]
        assert "conversation" in classes and "tool_result" in classes


def test_stats_shape_and_counts():
    ap = build()
    with ap.chat("s") as chat:
        for i in range(3):
            chat.send(f"turn {i} with some text to send")
        stats = chat.stats()
    assert stats["calls"] == 3
    assert stats["input_tokens"] > 0
    assert stats["cost_usd"] >= 0.0
    assert 0.0 <= stats["cache_hit_rate"] <= 1.0
    assert "bytes_dropped" in stats and "spans_dropped" in stats


def test_clean_exit_records_success_outcome(tmp_path):
    from aperture.trace.ledger import TraceLedger

    ledger = TraceLedger(tmp_path / "t.jsonl")
    ap = build(ledger=ledger)
    with ap.chat("s") as chat:
        chat.send("one")
        chat.send("two")
    outcomes = [r.outcome for r in ledger.join_outcomes()]
    assert len(outcomes) == 2
    assert all(o.task_success for o in outcomes)


def test_exception_records_failure_and_propagates(tmp_path):
    from aperture.trace.ledger import TraceLedger

    ledger = TraceLedger(tmp_path / "t.jsonl")
    ap = build(ledger=ledger)
    with pytest.raises(RuntimeError), ap.chat("s") as chat:
        chat.send("one")
        raise RuntimeError("task blew up")
    outcomes = [r.outcome for r in ledger.join_outcomes()]
    assert outcomes and outcomes[0].task_success is False


def test_profiles_change_selector_thresholds():
    lean = build(profile="lean")
    safe = build(profile="safe")
    off = build(profile="off")
    assert lean.selector.threshold < safe.selector.threshold
    assert off.selector.select(_features(0.99)) == []
    with pytest.raises(ValueError):
        build(profile="turbo")


def _features(frac):
    from aperture.session import Features

    return Features(
        budget_used_frac=frac,
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash="x",
    )


def test_selector_kwarg_wins_over_profile():
    sel = HeuristicSelector(threshold=0.2)
    ap = build(profile="safe", selector=sel)
    assert ap.selector is sel


def test_session_ids_do_not_collide():
    ap = build()
    with ap.chat() as chat1:
        chat1.send("a")
    with ap.chat() as chat2:
        chat2.send("b")
    assert chat1.raw.session_id != chat2.raw.session_id


def test_stats_helpful_repr():
    ap = build()
    with ap.chat("s") as chat:
        chat.send("hello")
    text = repr(chat)
    assert "calls" in text and "1" in text
