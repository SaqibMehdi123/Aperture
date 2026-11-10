"""LangGraph adapter (spec Table 6 P1: "LangGraph + raw-loop adapters").

Contract: wrap_node makes any LangGraph node aperture-managed. The adapter
owns history sync (state messages -> spans, per thread), injects
`state["aperture"]` with a `.complete()` handle, and keeps window and state
in lockstep so nothing is ingested twice. No `langgraph` dependency is
needed to test: messages may be plain dicts or LangChain-style objects.
"""

from types import SimpleNamespace

from adapters.langgraph import LangGraphAdapter
from aperture import Aperture


def build_adapter():
    return LangGraphAdapter(Aperture())


def invoke(adapter, node, state, config=None):
    wrapped = adapter.wrap_node(node)
    if config is None:
        return wrapped(state)
    return wrapped(state, config)


def node_uses_aperture(state):
    reply = state["aperture"].complete()
    return {"messages": [{"role": "assistant", "content": reply}]}


def test_wrap_node_returns_node_result():
    lg = build_adapter()
    out = invoke(lg, node_uses_aperture, {"messages": [{"role": "user", "content": "hi"}]})
    assert out["messages"][0]["role"] == "assistant"
    assert out["messages"][0]["content"]


def test_window_mirrors_state_without_duplicates():
    lg = build_adapter()
    invoke(lg, node_uses_aperture, {"messages": [{"role": "user", "content": "hi"}]})
    invoke(
        lg,
        node_uses_aperture,
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "user", "content": "more"},
            ]
        },
    )
    chat = lg.session_for("default")
    classes = [c for c, _ in chat.history()]
    # user, assistant, user, assistant - exactly once each
    assert classes == ["conversation", "assistant", "conversation", "assistant"]


def test_system_message_becomes_protected_head():
    lg = build_adapter()
    state = {
        "messages": [
            {"role": "system", "content": "be careful"},
            {"role": "user", "content": "hi"},
        ]
    }
    invoke(lg, node_uses_aperture, state)
    chat = lg.session_for("default")
    sys_span = chat.raw.window.spans[0]
    assert sys_span.span_class == "system"
    assert sys_span.pinned and sys_span.protected and sys_span.cache_head


def test_tool_messages_map_to_tool_result_class():
    lg = build_adapter()

    def node(state):
        state["aperture"].complete()
        return {"messages": [{"role": "assistant", "content": "done"}]}

    invoke(
        lg,
        node,
        {
            "messages": [
                {"role": "user", "content": "run it"},
                {"role": "tool", "content": "[tool] batch output"},
            ]
        },
    )
    classes = [c for c, _ in lg.session_for("default").history()]
    assert "tool_result" in classes


def test_langchain_style_message_objects():
    lg = build_adapter()

    def node(state):
        return {"messages": [SimpleNamespace(type="ai", content="obj reply")]}

    invoke(
        lg,
        node,
        {"messages": [SimpleNamespace(type="human", content="obj question")]},
    )
    chat = lg.session_for("default")
    assert chat.history()[0] == ("conversation", "obj question")
    assert chat.history()[1] == ("assistant", "obj reply")


def test_node_that_does_not_call_aperture_still_syncs():
    lg = build_adapter()

    def plain_node(state):
        return {"messages": [{"role": "assistant", "content": "bypassed"}]}

    invoke(lg, plain_node, {"messages": [{"role": "user", "content": "q"}]})
    chat = lg.session_for("default")
    assert [c for c, _ in chat.history()] == ["conversation", "assistant"]


def test_threads_are_isolated():
    lg = build_adapter()
    invoke(
        lg,
        node_uses_aperture,
        {"messages": [{"role": "user", "content": "thread one"}]},
        config={"configurable": {"thread_id": "t1"}},
    )
    invoke(
        lg,
        node_uses_aperture,
        {"messages": [{"role": "user", "content": "thread two"}]},
        config={"configurable": {"thread_id": "t2"}},
    )
    assert ("conversation", "thread one") in lg.session_for("t1").history()
    assert ("conversation", "thread two") in lg.session_for("t2").history()
    assert all(c != "conversation" or "two" not in t for c, t in lg.session_for("t1").history())


def test_session_ids_namespaced_by_thread():
    lg = build_adapter()
    invoke(
        lg,
        node_uses_aperture,
        {"messages": [{"role": "user", "content": "x"}]},
        config={"configurable": {"thread_id": "t-9"}},
    )
    assert lg.session_for("t-9").raw.session_id == "lg-t-9"


def test_stats_reachable_from_state():
    lg = build_adapter()

    def node(state):
        state["aperture"].complete()
        assert state["aperture"].stats()["calls"] == 1
        return {"messages": [{"role": "assistant", "content": "ok"}]}

    invoke(lg, node, {"messages": [{"role": "user", "content": "hi"}]})


def test_reset_clears_thread():
    lg = build_adapter()
    invoke(lg, node_uses_aperture, {"messages": [{"role": "user", "content": "hi"}]})
    lg.reset("default")
    invoke(lg, node_uses_aperture, {"messages": [{"role": "user", "content": "fresh"}]})
    classes = [c for c, _ in lg.session_for("default").history()]
    assert classes == ["conversation", "assistant"]  # old turns gone


def test_replay_and_ledger_still_work_through_adapter(tmp_path):
    from aperture.trace.ledger import TraceLedger

    lg = LangGraphAdapter(Aperture(ledger=TraceLedger(tmp_path / "t.jsonl")))
    invoke(lg, node_uses_aperture, {"messages": [{"role": "user", "content": "hi"}]})
    rec = next(iter(lg._runtime.ledger.records()))
    assert rec.schema_ == "curatebench/trace@v2"
    assert rec.features.prefix_hash
