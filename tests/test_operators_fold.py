"""P1 operators: dedupe + summarize (spec Table 6 P1, "seven operators").

Both fold or remove redundant content while respecting the guardrail: the
cache-stable head and pinned/protected spans are never touched, and diffs stay
deterministic so replay (G2) can reproduce them bit-identically.
"""

from aperture.operators import available, get
from aperture.operators.dedupe import Dedupe
from aperture.operators.summarize import Summarize
from aperture.session import Features, Span, Window

TOOL_ROW = "row: 42 items shipped to Berlin with tracking BX-4471 and customs form C-22 attached"
TURN = (
    "please summarize the quarterly refund report for the EU region and send it to the finance team"
)


def make_window(extra: list[Span] | None = None) -> Window:
    spans = [
        Span(
            span_id="sys",
            span_class="system",
            content="system prompt",
            cache_head=True,
            pinned=True,
        ),
        Span(
            span_id="c0", span_class="constraint", content="never leak", pinned=True, protected=True
        ),
        Span(span_id="u0", span_class="conversation", content="  " + TURN + "  "),
        Span(span_id="t0", span_class="tool_result", content=TOOL_ROW),
        Span(span_id="u1", span_class="conversation", content=TURN),
        Span(span_id="t1", span_class="tool_result", content=TOOL_ROW),
        Span(
            span_id="t2",
            span_class="tool_result",
            content="unique tool payload about invoices due in March",
        ),
    ]
    if extra:
        spans.extend(extra)
    return Window(token_budget=32768, spans=spans, step=5)


def _features(w):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
    )


# ---------------------------------------------------------------- dedupe ---
def test_dedupe_registered():
    assert "dedupe" in available()
    assert get("dedupe").name == "dedupe"


def test_dedupe_keeps_most_recent_duplicate_by_default():
    diff = Dedupe().apply(make_window(), _features(make_window()), {})
    dropped = {d.span_id: d for d in diff.dropped_spans}
    assert "t0" in dropped  # earlier duplicate of t1 dropped
    assert "t1" not in dropped  # most recent kept
    assert dropped["t0"].reason.startswith("dedupe")
    assert diff.cache_head_unchanged is True


def test_dedupe_keep_first():
    diff = Dedupe().apply(make_window(), _features(make_window()), {"keep": "first"})
    dropped = {d.span_id for d in diff.dropped_spans}
    assert "t0" not in dropped and "t1" in dropped


def test_dedupe_normalizes_whitespace_and_case():
    # u0 and u1 normalize to the same text (whitespace + case folded)
    diff = Dedupe().apply(make_window(), _features(make_window()), {})
    dropped = {d.span_id for d in diff.dropped_spans}
    assert "u0" in dropped and "u1" not in dropped


def test_dedupe_never_touches_head_pinned_protected():
    w = make_window(
        extra=[
            Span(span_id="sys2", span_class="system", content=TOOL_ROW, cache_head=True),
            Span(
                span_id="p0",
                span_class="constraint",
                content="unique tool payload about invoices due in March",
                pinned=True,
            ),
        ]
    )
    diff = Dedupe().apply(w, _features(w), {})
    dropped = {d.span_id for d in diff.dropped_spans}
    assert "sys2" not in dropped and "p0" not in dropped and "c0" not in dropped


def test_dedupe_min_tokens_guard():
    w = Window(
        token_budget=10**6,
        spans=[
            Span(span_id="a", span_class="conversation", content="ok"),
            Span(span_id="b", span_class="conversation", content="ok"),
            Span(span_id="c", span_class="conversation", content="ok"),
        ],
    )
    diff = Dedupe().apply(w, _features(w), {})  # min_tokens default keeps short turns
    assert len(diff.dropped_spans) == 0
    diff2 = Dedupe().apply(w, _features(w), {"min_tokens": 1})
    assert len(diff2.dropped_spans) == 2


def test_dedupe_cost_hint_cheap():
    assert Dedupe().cost_hint(make_window(), {}) <= len(make_window().spans)


# ------------------------------------------------------------- summarize ---
def test_summarize_registered():
    assert "summarize" in available()
    assert get("summarize").name == "summarize"


def test_summarize_folds_oldest_droppable_spans():
    op = Summarize()
    w = make_window()
    diff = op.apply(w, _features(w), {"max_spans": 3})
    assert len(diff.dropped_spans) == 3
    assert [d.span_id for d in diff.dropped_spans] == ["u0", "t0", "u1"]
    assert len(diff.new_spans) == 1
    new = diff.new_spans[0]
    assert new.summary_of == ("u0", "t0", "u1")
    assert diff.cache_head_unchanged is True


def test_summarize_never_folds_head_pinned_protected():
    op = Summarize()
    w = make_window()
    diff = op.apply(w, _features(w), {"max_spans": 10})
    dropped = {d.span_id for d in diff.dropped_spans}
    assert "sys" not in dropped and "c0" not in dropped


def test_summarize_uses_custom_summarizer():
    seen = []

    def my_summarizer(contents: list[str]) -> str:
        seen.extend(contents)
        return "CUSTOM SUMMARY"

    op = Summarize(summarizer=my_summarizer)
    w = make_window()
    diff = op.apply(w, _features(w), {"max_spans": 2})
    assert diff.new_spans[0].content == "CUSTOM SUMMARY"
    assert len(seen) == 2


def test_summarize_default_extractive_is_bounded():
    op = Summarize()
    long = "word " * 300  # ~1200 chars, no sentence break
    w = Window(
        token_budget=10**6,
        spans=[Span(span_id=f"t{i}", span_class="tool_result", content=long) for i in range(2)],
    )
    diff = op.apply(w, _features(w), {"max_spans": 2, "per_span_chars": 40})
    content = diff.new_spans[0].content
    assert len(content) < 200  # two capped fragments + newline
    assert diff.new_spans[0].bytes == len(content.encode())


def test_summarize_span_id_deterministic():
    w = make_window()
    d1 = Summarize().apply(w, _features(w), {"max_spans": 2})
    d2 = Summarize().apply(w, _features(w), {"max_spans": 2})
    assert d1.new_spans[0].span_id == d2.new_spans[0].span_id


def test_summarize_noop_when_nothing_droppable():
    w = Window(
        token_budget=10**6,
        spans=[Span(span_id="s", span_class="system", content="sys", cache_head=True, pinned=True)],
    )
    diff = Summarize().apply(w, _features(w), {"max_spans": 3})
    assert len(diff.dropped_spans) == 0 and len(diff.new_spans) == 0
