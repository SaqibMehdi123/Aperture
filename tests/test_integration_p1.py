"""P1 integration test: the runtime end to end on a long synthetic run.

Scenario: 60 turns, each adding a user message plus a bulky tool output,
under a 4000-token budget. Two arms, same deterministic gateway:

- full_history (profile="off"): nothing is ever curated
- aperture (profile="balanced"): threshold-triggered keep_recent

Assertions mirror the P1/G1 story: curation cuts cumulative input tokens
well below full history, governance constraints survive every decision,
prefix-cache hits materialize from the stable head, dropped content is
archived and retrievable, and every step writes a schema-v2 trace line.
"""

from adapters.langgraph import LangGraphAdapter
from aperture import Aperture
from aperture.operators.semantic_retrieval import SemanticRetrieval
from aperture.store import ArchiveView
from aperture.trace.ledger import TraceLedger

TURNS = 60
BUDGET = 4000
TOOL_OUTPUT = "log line payload for the batch job run " * 15  # ~570 chars
CONSTRAINT = "Never approve refunds above 500 USD without escalation."


def run_arm(tmp_path, name, profile, ledger_path):
    ledger = TraceLedger(tmp_path / ledger_path)
    ap = Aperture(profile=profile, ledger=ledger)
    with ap.chat(name, token_budget=BUDGET) as chat:
        chat.system("You are a careful operations agent.")
        chat.constraints([CONSTRAINT])
        chat.raw.register_probe("policy-intact", "constraint", "Never approve refunds")
        for i in range(TURNS):
            chat.send(f"turn {i}: please analyze the latest batch job output")
            chat.send(f"[{i}] {TOOL_OUTPUT}", role="tool")
        stats = chat.stats()
    return ap, ledger, stats


def test_p1_end_to_end_savings_safety_and_retrieval(tmp_path):
    full_ap, full_ledger, full_stats = run_arm(tmp_path, "full-hist", "off", "full.jsonl")
    ap_ap, ap_ledger, ap_stats = run_arm(tmp_path, "aperture", "balanced", "ap.jsonl")

    # 1. Both arms completed every step (equal task success by construction).
    assert full_stats["calls"] == TURNS * 2
    assert ap_stats["calls"] == TURNS * 2

    # 2. Curation saves well over 30% of cumulative input tokens (G1 shape).
    assert ap_stats["input_tokens"] < 0.7 * full_stats["input_tokens"]
    assert ap_stats["bytes_dropped"] > 0

    # 3. Governance constraints survived every curation decision (AG2).
    for rec in ap_ledger.records():
        assert rec.probes and all(p.survived for p in rec.probes)
    final_window = ap_ap.store.get("aperture", TURNS * 2 - 1)
    assert final_window.find("aperture-s2") is not None  # constraint span intact

    # 4. The stable head earns prefix-cache hits (AG1).
    assert ap_stats["cache_hit_rate"] > 0.9

    # 5. Nothing is lost: drops are archived and retrievable.
    hits = ap_ap.store.archive_search("aperture", "batch job", top_k=2)
    assert hits, "dropped tool outputs must be archived"
    view = ArchiveView(ap_ap.store, "aperture")
    diff = SemanticRetrieval().apply(
        final_window,
        _features(final_window, view),
        {"query": "earlier batch job output", "top_k": 1},
    )
    assert len(diff.new_spans) == 1
    assert "batch job" in diff.new_spans[0].content

    # 6. Every step is a versioned, replayable trace line.
    records = list(ap_ledger.records())
    assert len(records) == TURNS * 2
    assert all(r.schema_ == "curatebench/trace@v2" for r in records)
    assert any(d.op == "keep_recent" for r in records for d in r.plan)


def _features(window, archive):
    from aperture.session import Features

    return Features(
        budget_used_frac=window.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=window.prefix_hash(),
        archive=archive,
    )


def test_p1_end_to_end_langgraph_thread(tmp_path):
    """The same story through the LangGraph adapter path."""
    from aperture.trace.ledger import TraceLedger

    lg = LangGraphAdapter(
        Aperture(profile="balanced", ledger=TraceLedger(tmp_path / "lg.jsonl")),
        token_budget=BUDGET,
    )
    node = lg.wrap_node(
        lambda state: {"messages": [{"role": "assistant", "content": state["aperture"].complete()}]}
    )
    messages = [{"role": "system", "content": "You are a careful operations agent."}]
    for i in range(10):
        messages.append({"role": "user", "content": f"turn {i}: analyze batch output"})
        messages.append({"role": "tool", "content": f"[{i}] {TOOL_OUTPUT}"})
        out = node({"messages": list(messages)}, {"configurable": {"thread_id": "it"}})
        messages.append(out["messages"][0])

    chat = lg.session_for("it")
    stats = chat.stats()
    assert stats["calls"] == 10
    assert stats["input_tokens"] > 0
    # system + 30 turns + replies, no duplicates ingested
    classes = [c for c, _ in chat.history()]
    assert classes[0] == "system"
    assert classes.count("conversation") == 10
    assert classes.count("tool_result") == 10
