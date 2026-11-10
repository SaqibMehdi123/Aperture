"""Context Plane store (spec 7.1): versioned, addressable window snapshots plus
the content archive ("nothing is ever really lost").

Two implementations share one interface:

- `SpanStore` - in-memory; the CI/replay default (zero config).
- `SqliteSpanStore` - the same interface backed by one SQLite file; snapshots
  and archived content survive across processes (Phase P1 "pinned store").

Every span a curation decision drops is archived by the runtime under its
(session, span) key. Archive reads go through `ArchiveView`, the per-session
handle the runtime hands to retrieval operators via `Features.archive`.

Nothing here is provider-specific or heavy: sqlite3 is stdlib, and the
in-memory store keeps tests and replay deterministic.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from aperture.session import Window


@dataclass(frozen=True)
class ArchivedSpan:
    """One archived (dropped) span, retrievable by id or lexical search."""

    session_id: str
    span_id: str
    span_class: str
    content: str
    step: int
    nbytes: int


def _tokenize(text: str) -> set[str]:
    import re

    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _lexical_score(query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_tokens = _tokenize(content)
    if not content_tokens:
        return 0.0
    overlap = len(query_tokens & content_tokens)
    return overlap / len(query_tokens | content_tokens)


class SpanStore:
    """In-memory snapshots + archive, keyed by (session_id, step / span_id)."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, int], Window] = {}
        self._archive: dict[tuple[str, str], ArchivedSpan] = {}

    # -- snapshots ---------------------------------------------------------
    def put(self, session_id: str, step: int, window: Window) -> None:
        self._snapshots[(session_id, step)] = window.clone()

    def get(self, session_id: str, step: int) -> Window | None:
        window = self._snapshots.get((session_id, step))
        return window.clone() if window is not None else None

    def sessions(self) -> list[str]:
        return sorted({sid for sid, _ in self._snapshots})

    # -- archive -----------------------------------------------------------
    def archive_put(
        self, session_id: str, span_id: str, span_class: str, content: str, step: int, nbytes: int
    ) -> None:
        key = (session_id, span_id)
        self._archive[key] = ArchivedSpan(
            session_id=session_id,
            span_id=span_id,
            span_class=span_class,
            content=content,
            step=step,
            nbytes=nbytes,
        )

    def archive_recent(self, session_id: str, k: int = 10) -> list[ArchivedSpan]:
        items = [a for (sid, _), a in self._archive.items() if sid == session_id]
        return sorted(items, key=lambda a: a.step, reverse=True)[:k]

    def archive_search(
        self,
        session_id: str,
        query: str,
        top_k: int = 3,
        min_score: float = 0.05,
        span_class: str | None = None,
    ) -> list[ArchivedSpan]:
        qtokens = _tokenize(query)
        scored = [
            (_lexical_score(qtokens, a.content), a)
            for (sid, _), a in self._archive.items()
            if sid == session_id and (span_class is None or a.span_class == span_class)
        ]
        scored = [(s, a) for s, a in scored if s >= min_score]
        scored.sort(key=lambda pair: (-pair[0], -pair[1].step))
        return [a for _, a in scored[:top_k]]


class SqliteSpanStore(SpanStore):
    """Persistent snapshots + archive in one SQLite file.

    Drop-in for `SpanStore`: same methods, plus durability. `:memory:` keeps
    everything in RAM (tests), a path persists across processes.
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                session_id TEXT NOT NULL,
                step INTEGER NOT NULL,
                window_json TEXT NOT NULL,
                PRIMARY KEY (session_id, step)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS archive (
                session_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                span_class TEXT NOT NULL,
                content TEXT NOT NULL,
                step INTEGER NOT NULL,
                nbytes INTEGER NOT NULL,
                PRIMARY KEY (session_id, span_id)
            )
            """
        )
        self._conn.commit()

    def put(self, session_id: str, step: int, window: Window) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots (session_id, step, window_json) VALUES (?, ?, ?)",
            (session_id, step, json.dumps(window.to_dict())),
        )
        self._conn.commit()

    def get(self, session_id: str, step: int) -> Window | None:
        row = self._conn.execute(
            "SELECT window_json FROM snapshots WHERE session_id = ? AND step = ?",
            (session_id, step),
        ).fetchone()
        return Window.from_dict(json.loads(row[0])) if row is not None else None

    def sessions(self) -> list[str]:
        rows = self._conn.execute("SELECT DISTINCT session_id FROM snapshots").fetchall()
        return sorted(r[0] for r in rows)

    def archive_put(
        self, session_id: str, span_id: str, span_class: str, content: str, step: int, nbytes: int
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO archive"
            " (session_id, span_id, span_class, content, step, nbytes)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, span_id, span_class, content, step, nbytes),
        )
        self._conn.commit()

    def _archive_rows(self, session_id: str) -> list[ArchivedSpan]:
        rows = self._conn.execute(
            "SELECT session_id, span_id, span_class, content, step, nbytes FROM archive"
            " WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        return [ArchivedSpan(*row) for row in rows]

    def archive_recent(self, session_id: str, k: int = 10) -> list[ArchivedSpan]:
        return sorted(self._archive_rows(session_id), key=lambda a: a.step, reverse=True)[:k]

    def archive_search(
        self,
        session_id: str,
        query: str,
        top_k: int = 3,
        min_score: float = 0.05,
        span_class: str | None = None,
    ) -> list[ArchivedSpan]:
        qtokens = _tokenize(query)
        rows = [
            a
            for a in self._archive_rows(session_id)
            if span_class is None or a.span_class == span_class
        ]
        scored = [(_lexical_score(qtokens, a.content), a) for a in rows]
        scored = [(s, a) for s, a in scored if s >= min_score]
        scored.sort(key=lambda pair: (-pair[0], -pair[1].step))
        return [a for _, a in scored[:top_k]]


class ArchiveView:
    """Per-session, read-only archive handle for operators (via Features.archive).

    Operators stay pure: they see only this view for their own session, never
    the whole store. `search()` is the P1 lexical scorer; a pluggable embedder
    upgrades it in P4 without changing call sites.
    """

    def __init__(self, store: SpanStore | SqliteSpanStore, session_id: str) -> None:
        self._store = store
        self._session_id = session_id

    def search(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.05,
        span_class: str | None = None,
    ) -> list[ArchivedSpan]:
        return self._store.archive_search(
            self._session_id, query, top_k=top_k, min_score=min_score, span_class=span_class
        )

    def recent(self, k: int = 10) -> list[ArchivedSpan]:
        return self._store.archive_recent(self._session_id, k=k)

    def __len__(self) -> int:
        return len(self._store.archive_recent(self._session_id, k=10**9))
