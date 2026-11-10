"""Context Plane store: snapshots + the content archive (P1, spec 7.1).

The archive is the "nothing is ever really lost" guarantee: every span a
curation decision drops is archived by the runtime, so retrieval operators
(P1) and the observability layer can bring it back. The SQLite store makes
snapshots and the archive persistent across processes.
"""

import pytest
from aperture.session import Span, Window
from aperture.store import ArchiveView, SpanStore, SqliteSpanStore


def make_window(step: int = 0) -> Window:
    spans = [
        Span(span_id="sys", span_class="system", content="you are helpful", cache_head=True),
        Span(span_id="t0", span_class="tool_result", content="big tool output " * 50),
        Span(span_id="u0", span_class="conversation", content="hello there"),
    ]
    return Window(token_budget=32768, spans=spans, step=step)


@pytest.mark.parametrize(
    "store_factory", [lambda: SpanStore(), lambda: SqliteSpanStore(":memory:")]
)
def test_put_get_snapshot_roundtrip(store_factory):
    store = store_factory()
    w = make_window(step=3)
    store.put("s1", 3, w)
    got = store.get("s1", 3)
    assert got is not None
    assert [s.span_id for s in got.spans] == ["sys", "t0", "u0"]
    assert got.token_budget == 32768
    assert store.get("s1", 4) is None


@pytest.mark.parametrize(
    "store_factory", [lambda: SpanStore(), lambda: SqliteSpanStore(":memory:")]
)
def test_sessions_listing(store_factory):
    store = store_factory()
    store.put("b", 0, make_window())
    store.put("a", 0, make_window())
    assert store.sessions() == ["a", "b"]


@pytest.mark.parametrize(
    "store_factory", [lambda: SpanStore(), lambda: SqliteSpanStore(":memory:")]
)
def test_archive_put_and_recent(store_factory):
    store = store_factory()
    store.archive_put("s1", "t-old", "tool_result", "old content", step=2, nbytes=11)
    store.archive_put("s1", "t-older", "tool_result", "older content", step=1, nbytes=13)
    rec = store.archive_recent("s1", k=1)
    assert len(rec) == 1
    assert rec[0].span_id == "t-old"  # most recent first
    assert rec[0].content == "old content"
    assert rec[0].session_id == "s1"


@pytest.mark.parametrize(
    "store_factory", [lambda: SpanStore(), lambda: SqliteSpanStore(":memory:")]
)
def test_archive_search_lexical_scoring(store_factory):
    store = store_factory()
    store.archive_put(
        "s1", "a", "tool_result", "refund policy for orders in the EU", step=1, nbytes=30
    )
    store.archive_put("s1", "b", "tool_result", "weather report: sunny all week", step=2, nbytes=30)
    store.archive_put("s1", "c", "tool_result", "EU refund window is 30 days", step=3, nbytes=30)
    hits = store.archive_search("s1", "how does the EU refund policy work", top_k=2)
    assert [h.span_id for h in hits][0] in {"a", "c"}
    assert "b" not in [h.span_id for h in hits]


def test_sqlite_store_persists_across_reopen(tmp_path):
    db = str(tmp_path / "aperture.db")
    store = SqliteSpanStore(db)
    store.put("s1", 5, make_window(step=5))
    store.archive_put("s1", "t0", "tool_result", "archived body", step=5, nbytes=14)

    reopened = SqliteSpanStore(db)
    assert reopened.get("s1", 5) is not None
    assert reopened.get("s1", 5).find("t0").content.startswith("big tool output")
    assert reopened.archive_recent("s1", k=5)[0].content == "archived body"


def test_archive_view_scopes_and_searches():
    store = SpanStore()
    store.archive_put(
        "s1", "a", "tool_result", "the api key rotation policy is 90 days", step=1, nbytes=10
    )
    store.archive_put(
        "s2", "b", "tool_result", "unrelated other session content", step=1, nbytes=10
    )
    view = ArchiveView(store, "s1")
    hits = view.search("api key rotation", top_k=3)
    assert len(hits) == 1 and hits[0].span_id == "a"
    assert view.recent(k=5)[0].span_id == "a"


def test_window_serialization_roundtrip():
    w = make_window(step=7)
    w2 = Window.from_dict(w.to_dict())
    assert w2.token_budget == w.token_budget
    assert w2.step == 7
    assert [s.span_id for s in w2.spans] == [s.span_id for s in w.spans]
    assert w2.spans[0].cache_head and not w2.spans[1].pinned


def test_archive_search_filters_by_span_class():
    """Class-filtered retrieval: a tool-output query must not return chat turns."""
    store = SpanStore()
    store.archive_put("s1", "conv", "conversation", "Log batch 1 now.", step=1, nbytes=16)
    store.archive_put(
        "s1", "data", "tool_result", "[batch 1] readings: 45.2 31.7 88.1", step=2, nbytes=32
    )
    hits = store.archive_search("s1", "batch 1", top_k=3, span_class="tool_result")
    assert [h.span_id for h in hits] == ["data"]
    # unfiltered search keeps the old behavior (both classes eligible)
    assert len(store.archive_search("s1", "batch 1", top_k=3)) == 2
