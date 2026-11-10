"""Contracts (AG5) and the span store."""

from aperture.contracts import ContextContract, ContractRegistry
from aperture.session import Span, Window
from aperture.store import SpanStore


def test_contract_roundtrip_fields():
    c = ContextContract(
        task_id="t1",
        objective="summarize tool outputs",
        token_budget=900,
        allowed_classes=frozenset({"tool_result", "summary"}),
        ttl_steps=5,
        provenance=("agent://main",),
        return_schema="{}",
    )
    assert c.token_budget == 900
    assert "tool_result" in c.allowed_classes


def test_registry_ttl_expiry():
    c = ContextContract(
        task_id="t1",
        objective="x",
        token_budget=100,
        allowed_classes=frozenset({"tool_result"}),
        ttl_steps=2,
        provenance=(),
        return_schema="{}",
    )
    reg = ContractRegistry()
    reg.register(c, step=0)
    assert reg.get("t1") is c
    assert len(reg.active(step=2)) == 1
    assert reg.active(step=3) == []  # TTL expired


def test_validate_window_budget_and_classes():
    c = ContextContract(
        task_id="t1",
        objective="x",
        token_budget=10,
        allowed_classes=frozenset({"tool_result"}),
        ttl_steps=5,
        provenance=(),
        return_schema="{}",
    )
    reg = ContractRegistry()
    w = Window(
        token_budget=10**6,
        spans=[
            Span(span_id="a", span_class="tool_result", content="fine"),
            Span(span_class="conversation", span_id="b", content="x" * 100),  # wrong class, too big
        ],
    )
    violations = reg.validate_window(c, w)
    assert any(v.startswith("budget") for v in violations)
    assert any(v.startswith("class") for v in violations)


def test_span_store_versioned():
    store = SpanStore()
    w1 = Window(token_budget=10, spans=[Span(span_id="a", span_class="system", content="v1")])
    store.put("s", 0, w1)
    w1.spans.append(Span(span_id="b", span_class="tool_result", content="v2"))
    store.put("s", 1, w1)
    snap0 = store.get("s", 0)
    assert len(snap0.spans) == 1  # step-0 snapshot untouched
    snap0.spans.append(Span(span_id="z", span_class="tool_result", content="mutate"))
    assert len(store.get("s", 0).spans) == 1  # store returns isolated clones
    assert store.sessions() == ["s"]
    assert store.get("s", 99) is None
