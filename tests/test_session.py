"""Context Plane types: Span, Window, fingerprints (spec 7.4 session.py)."""

from aperture.session import Span, Window, estimate_tokens


def test_estimate_tokens_deterministic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("ab") == 1  # never zero for non-empty
    assert estimate_tokens("a" * 401) == 101


def test_span_bytes_and_tokens():
    s = Span(span_id="s1", span_class="tool_result", content="hello world")
    assert s.bytes == len(b"hello world")
    assert s.tokens == (s.bytes + 3) // 4


def test_window_accounting_and_budget_cap():
    w = Window(token_budget=10)
    w.spans.append(Span(span_id="a", span_class="tool_result", content="x" * 40))  # 10 tok
    w.spans.append(Span(span_id="b", span_class="tool_result", content="y" * 40))
    assert w.total_tokens() == 20
    assert w.used_frac() == 1.0  # capped, never > 1


def test_head_fingerprint_stability():
    head = Span(span_id="sys", span_class="system", content="system prompt", cache_head=True)
    tail = Span(span_id="t1", span_class="tool_result", content="tool output")
    w = Window(token_budget=1000, spans=[head, tail])
    fp_before = w.head_fingerprint()
    w.spans.append(Span(span_id="t2", span_class="tool_result", content="more"))
    assert w.head_fingerprint() == fp_before  # tail growth does not move the head

    w.spans[0] = head.with_meta(x="1")  # metadata does not change content bytes
    assert w.head_fingerprint() == fp_before
    w.spans[0] = Span(span_id="sys", span_class="system", content="changed", cache_head=True)
    assert w.head_fingerprint() != fp_before  # head edit invalidates the cache prefix


def test_prefix_hash_moves_with_tail():
    head = Span(span_id="sys", span_class="system", content="system", cache_head=True)
    w = Window(token_budget=1000, spans=[head])
    h1 = w.prefix_hash()
    w.spans.append(Span(span_id="t", span_class="tool_result", content="x"))
    assert w.prefix_hash() != h1


def test_find_and_clone():
    a = Span(span_id="a", span_class="system", content="a", cache_head=True)
    w = Window(token_budget=10, spans=[a])
    assert w.find("a") is a
    assert w.find("zz") is None
    w2 = w.clone()
    w2.spans.append(Span(span_id="b", span_class="tool_result", content="b"))
    assert len(w.spans) == 1  # clone is shallow-independent
    assert w2.token_budget == w.token_budget
