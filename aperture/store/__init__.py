"""Context Plane store (spec 7.1): versioned, addressable window snapshots.

P0 ships the in-memory store the replay engine needs; SQLite + object store
land with Phase P1/P2.
"""

from __future__ import annotations

from aperture.session import Window


class SpanStore:
    """Versioned snapshots keyed by (session_id, step)."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, int], Window] = {}

    def put(self, session_id: str, step: int, window: Window) -> None:
        self._snapshots[(session_id, step)] = window.clone()

    def get(self, session_id: str, step: int) -> Window | None:
        window = self._snapshots.get((session_id, step))
        return window.clone() if window is not None else None

    def sessions(self) -> list[str]:
        return sorted({sid for sid, _ in self._snapshots})
