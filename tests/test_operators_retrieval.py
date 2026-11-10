"""P1 operators: subagent_isolation + semantic_retrieval (spec Table 6 P1).

subagent_isolation stashes bulky tool outputs out of the live window behind a
compact stub (the runtime archives the full body). semantic_retrieval brings
archived content back when the conversation needs it. Together they close the
loop: drop big, find back - nothing is ever really lost.
"""

from types import SimpleNamespace

from aperture.operators import available, get
from aperture.operators.semantic_retrieval import SemanticRetrieval
from aperture.operators.subagent_isolation import SubagentIsolation
from aperture.session import Features, Span, Window
from aperture.store import SpanStore


class FakeArchive:
    """Minimal stand-in with the ArchiveView surface the operator uses.

    Rows are returned as SimpleNamespace objects, matching the ArchivedSpan
    attribute contract (span_id, span_class, content, step).
    """

    def __init__(self, rows):
        self._rows = rows

    def search(self, query, top_k=3, min_score=0.05):
        q = set(query.lower().split())
        scored = []
        for r in self._rows:
            tokens = set(r["content"].lower().split())
            if not q | tokens:
                continue
            score = len(q & tokens) / len(q | tokens)
            if score >= min_score:
                scored.append((score, r))
        scored.sort(key=lambda p: -p[0])
        return [SimpleNamespace(**r) for _, r in scored[:top_k]]

    def recent(self, k=10):
        return [SimpleNamespace(**r) for r in self._rows[:k]]


def big_output(tag: str, n: int = 400) -> Span:
    return Span(
        span_id=tag,
        span_class="tool_result",
        content=f"[{tag}] " + "log line payload for the batch job run " * n,
    )


def make_window(with_big: bool = True):
    spans = [
        Span(
            span_id="sys",
            span_class="system",
            content="system prompt",
            cache_head=True,
            pinned=True,
        ),
        Span(span_id="u0", span_class="conversation", content="run the batch job and summarize"),
    ]
    if with_big:
        spans.append(big_output("t0"))
    spans.append(Span(span_id="u1", span_class="conversation", content="thanks, what next?"))
    return Window(token_budget=32768, spans=spans, step=2)


def _features(w, archive=None):
    return Features(
        budget_used_frac=w.used_frac(),
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash=w.prefix_hash(),
        archive=archive,
    )


# --------------------------------------------------- subagent_isolation ---
def test_subagent_isolation_registered():
    assert "subagent_isolation" in available()
    assert get("subagent_isolation").name == "subagent_isolation"


def test_isolates_large_tool_outputs_behind_stub():
    w = make_window()
    diff = SubagentIsolation().apply(w, _features(w), {})
    assert [d.span_id for d in diff.dropped_spans] == ["t0"]
    assert len(diff.new_spans) == 1
    stub = diff.new_spans[0]
    assert stub.summary_of == ("t0",)
    assert "t0" in stub.content and str(w.find("t0").bytes) in stub.content
    assert stub.bytes < 200  # compact stub, not the payload


def test_small_outputs_left_alone():
    w = make_window(with_big=False)
    diff = SubagentIsolation().apply(w, _features(w), {})
    assert len(diff.dropped_spans) == 0 and len(diff.new_spans) == 0


def test_isolation_respects_min_bytes_param():
    w = make_window()
    diff = SubagentIsolation().apply(w, _features(w), {"min_bytes": 10**9})
    assert len(diff.dropped_spans) == 0


def test_isolation_never_touches_head_pinned_protected():
    w = make_window()
    w.spans.insert(1, big_output("p0"))
    w.spans[1] = Span(
        span_id="p0", span_class="tool_result", content=w.spans[1].content, pinned=True
    )
    diff = SubagentIsolation().apply(w, _features(w), {})
    dropped = {d.span_id for d in diff.dropped_spans}
    assert "p0" not in dropped and "t0" in dropped


def test_isolation_max_spans_param():
    w = make_window()
    w.spans.append(big_output("t1"))
    diff = SubagentIsolation().apply(w, _features(w), {"max_spans": 1})
    assert len(diff.dropped_spans) == 1  # largest one only


def test_isolation_stub_lands_in_successor_window():
    from aperture.engine import apply_diff

    w = make_window()
    w2 = apply_diff(w, SubagentIsolation().apply(w, _features(w), {}))
    assert w2.find("t0") is None  # original gone
    stub = w2.find("stub-t0")
    assert stub is not None and stub.summary_of == ("t0",)


# ---------------------------------------------------- semantic_retrieval ---
def test_semantic_retrieval_registered():
    assert "semantic_retrieval" in available()
    assert get("semantic_retrieval").name == "semantic_retrieval"


def test_retrieval_noop_without_archive():
    w = make_window()
    diff = SemanticRetrieval().apply(w, _features(w, archive=None), {})
    assert len(diff.new_spans) == 0 and len(diff.dropped_spans) == 0


def test_retrieval_pulls_relevant_archived_span():
    archive = FakeArchive(
        [
            {
                "span_id": "old-1",
                "span_class": "tool_result",
                "content": "batch job finished with 3 failed rows",
                "step": 0,
            },
            {
                "span_id": "old-2",
                "span_class": "tool_result",
                "content": "weather in berlin sunny",
                "step": 0,
            },
        ]
    )
    w = make_window()
    diff = SemanticRetrieval().apply(
        w, _features(w, archive), {"query": "why did the batch job fail", "top_k": 1}
    )
    assert len(diff.new_spans) == 1
    new = diff.new_spans[0]
    assert new.summary_of == ("old-1",)
    assert new.span_class == "retrieved"
    assert "batch job" in new.content
    assert len(diff.dropped_spans) == 0  # retrieval is non-destructive


def test_retrieval_skips_live_spans():
    archive = FakeArchive(
        [
            {
                "span_id": "t0",
                "span_class": "tool_result",
                "content": "log line payload for the batch job run",
                "step": 0,
            }
        ]
    )
    w = make_window()  # t0 is still live in the window
    diff = SemanticRetrieval().apply(
        w, _features(w, archive), {"query": "log line payload batch", "top_k": 3}
    )
    assert len(diff.new_spans) == 0  # already live: no duplicate injection


def test_retrieval_respects_min_score():
    archive = FakeArchive(
        [
            {
                "span_id": "old-9",
                "span_class": "tool_result",
                "content": "entirely unrelated content here",
                "step": 0,
            }
        ]
    )
    w = make_window()
    diff = SemanticRetrieval().apply(
        w, _features(w, archive), {"query": "batch job failure analysis", "min_score": 0.9}
    )
    assert len(diff.new_spans) == 0


def test_retrieval_truncates_content():
    archive = FakeArchive(
        [{"span_id": "old-1", "span_class": "tool_result", "content": "word " * 1000, "step": 0}]
    )
    w = make_window()
    diff = SemanticRetrieval().apply(w, _features(w, archive), {"query": "word", "max_chars": 200})
    assert diff.new_spans[0].bytes <= 200 + 50  # content + marker headroom


def test_retrieval_works_off_real_store_archive():
    store = SpanStore()
    store.archive_put(
        "s1", "old-1", "tool_result", "the refund policy allows 30 days", step=1, nbytes=10
    )
    from aperture.store import ArchiveView

    w = make_window()
    diff = SemanticRetrieval().apply(
        w, _features(w, ArchiveView(store, "s1")), {"query": "how long is the refund policy window"}
    )
    assert len(diff.new_spans) == 1 and "refund policy" in diff.new_spans[0].content
