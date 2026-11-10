"""Context Plane session types: Span, Window, Features/SessionView, WindowDiff.

These are the versioned, addressable state units that every operator reads and
writes (spec Section 7, "Context Plane"). A Span is an addressable unit of
context; a Window is an ordered span list under a token budget; SessionView is
the feature vector the selector sees each step; WindowDiff is the audit record
an operator returns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

# A span class names the content type; "constraint" spans are governance-
# protected (AG2). Classes are open strings so adapters can add their own.
SpanClass = str

SPAN_SYSTEM = "system"
SPAN_CONSTRAINT = "constraint"
SPAN_TOOL_RESULT = "tool_result"
SPAN_CONVERSATION = "conversation"
SPAN_SUMMARY = "summary"


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate (~4 chars/token). Replaced by gateway telemetry
    when available; kept deterministic so tests and replay are stable."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass(frozen=True)
class Span:
    """An addressable, immutable unit of context."""

    span_id: str
    span_class: SpanClass
    content: str
    created_step: int = 0
    pinned: bool = False
    protected: bool = False  # AG2: never silently destroyed
    cache_head: bool = False  # AG1: part of the cache-stable prefix
    summary_of: tuple[str, ...] = ()  # provenance for folded spans
    meta: dict[str, str] = field(default_factory=dict)

    @property
    def bytes(self) -> int:
        return len(self.content.encode("utf-8"))

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)

    def with_meta(self, **meta: str) -> Span:
        merged = dict(self.meta)
        merged.update(meta)
        return replace(self, meta=merged)


@dataclass
class Window:
    """An ordered span list under a token budget."""

    token_budget: int
    spans: list[Span] = field(default_factory=list)
    step: int = 0

    def total_tokens(self) -> int:
        return sum(s.tokens for s in self.spans)

    def total_bytes(self) -> int:
        return sum(s.bytes for s in self.spans)

    def used_frac(self) -> float:
        if self.token_budget <= 0:
            return 1.0
        return min(1.0, self.total_tokens() / self.token_budget)

    def head_spans(self) -> list[Span]:
        return [s for s in self.spans if s.cache_head]

    def head_fingerprint(self) -> str:
        """Stable fingerprint of the cache-stable prefix (AG1)."""
        return self._fingerprint([s for s in self.spans if s.cache_head])

    def prefix_hash(self) -> str:
        """Fingerprint of the full ordered prefix as the model would see it."""
        return self._fingerprint(self.spans)

    @staticmethod
    def _fingerprint(spans: list[Span]) -> str:
        payload = json.dumps([(s.span_id, s.bytes) for s in spans])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def find(self, span_id: str) -> Span | None:
        for s in self.spans:
            if s.span_id == span_id:
                return s
        return None

    def clone(self) -> Window:
        return Window(token_budget=self.token_budget, spans=list(self.spans), step=self.step)


@dataclass(frozen=True)
class Features:
    """Selector inputs, one per model call (spec 7.2 step 1; Appendix A `features`)."""

    budget_used_frac: float
    task_phase: str
    tool_output_tokens_recent: int
    redundancy_score: float
    drift_score: float
    prefix_hash: str


SessionView = Features  # the Agent Interface hands the engine a SessionView


def _features_dict(f: Features) -> dict[str, Any]:
    return {
        "budget_used_frac": f.budget_used_frac,
        "task_phase": f.task_phase,
        "tool_output_tokens_recent": f.tool_output_tokens_recent,
        "redundancy_score": f.redundancy_score,
        "drift_score": f.drift_score,
        "prefix_hash": f.prefix_hash,
    }


@dataclass(frozen=True)
class DroppedSpan:
    span_id: str
    reason: str
    bytes: int
    classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class NewSpan:
    span_id: str
    bytes: int
    summary_of: tuple[str, ...] = ()
    content: str = ""  # runtime field; not serialized into the trace schema


@dataclass(frozen=True)
class WindowDiff:
    """Audit record returned by every operator (spec 7.3)."""

    op: str
    kept_spans: tuple[str, ...] = ()
    dropped_spans: tuple[DroppedSpan, ...] = ()
    new_spans: tuple[NewSpan, ...] = ()
    cache_head_unchanged: bool = True
    probe_targets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "kept_spans": list(self.kept_spans),
            "dropped_spans": [
                {
                    "span_id": d.span_id,
                    "bytes": d.bytes,
                    "reason": d.reason,
                    "classes": list(d.classes),
                }
                for d in self.dropped_spans
            ],
            "new_spans": [
                {"span_id": n.span_id, "bytes": n.bytes, "summary_of": list(n.summary_of)}
                for n in self.new_spans
            ],
            "cache_head_unchanged": self.cache_head_unchanged,
        }
