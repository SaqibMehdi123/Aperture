"""CurateBench replay engine core (spec 7.4: `trace/replay.py`; AG3).

Counterfactual replay re-runs a recorded curation decision under an alternative
plan on the reconstructed window. Two properties matter:

- **Bit-identical reproduction** (gate G2): replaying a record's own plan on
  the reconstructed window reproduces the recorded diffs exactly. This test
  runs from Phase P0 onward.
- **Counterfactuals**: swapping the plan yields alternative diffs + metrics
  (tokens, dropped bytes, cache-head stability) that CurateBench scores.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from bench.schema import DiffRecord, TraceRecord

from aperture.engine import CurationEngine
from aperture.interfaces import PlannedOp
from aperture.session import Features, Window, WindowDiff


@dataclass(frozen=True)
class ReplayResult:
    window: Window
    diffs: tuple[WindowDiff, ...]
    trace_diffs: tuple[DiffRecord, ...]
    total_tokens: int
    dropped_bytes: int
    head_unchanged: bool


def plan_from_record(record: TraceRecord) -> list[PlannedOp]:
    return [
        PlannedOp(op=p.op, params=dict(p.params), order=p.order)
        for p in sorted(record.plan, key=lambda p: p.order)
    ]


def features_from_record(record: TraceRecord) -> Features:
    f = record.features
    return Features(
        budget_used_frac=f.budget_used_frac,
        task_phase=f.task_phase,
        tool_output_tokens_recent=f.tool_output_tokens_recent,
        redundancy_score=f.redundancy_score,
        drift_score=f.drift_score,
        prefix_hash=f.prefix_hash,
    )


def window_diff_to_record(diff: WindowDiff) -> DiffRecord:
    return DiffRecord(
        op=diff.op,
        dropped=[
            {
                "span_id": d.span_id,
                "bytes": d.bytes,
                "reason": d.reason,
                "classes": list(d.classes),
            }
            for d in diff.dropped_spans
        ],
        new_spans=[
            {"span_id": n.span_id, "bytes": n.bytes, "summary_of": list(n.summary_of)}
            for n in diff.new_spans
        ],
        pinned=[
            {
                "span_id": p.span_id,
                "pinned": p.pinned,
                "protected": p.protected,
                "cache_head": p.cache_head,
            }
            for p in diff.pinned
        ],
        cache_head_unchanged=diff.cache_head_unchanged,
    )


def diff_signature(diffs: list[DiffRecord] | tuple[DiffRecord, ...]) -> str:
    """Canonical fingerprint of a diff sequence - the bit-identical check."""
    payload = json.dumps(
        [d.model_dump(mode="json") for d in diffs], sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def replay_step(
    record: TraceRecord,
    window: Window,
    engine: CurationEngine | None = None,
    plan: list[PlannedOp] | None = None,
) -> ReplayResult:
    """Re-run one recorded step. `plan=None` replays the recorded plan;
    otherwise `plan` is the counterfactual."""
    engine = engine or CurationEngine()
    active_plan = plan if plan is not None else plan_from_record(record)
    composed, diffs = engine.compose(window, active_plan, features_from_record(record))
    trace_diffs = tuple(window_diff_to_record(d) for d in diffs)
    return ReplayResult(
        window=composed,
        diffs=tuple(diffs),
        trace_diffs=trace_diffs,
        total_tokens=composed.total_tokens(),
        dropped_bytes=sum(d.bytes for diff in diffs for d in diff.dropped_spans),
        head_unchanged=all(d.cache_head_unchanged for d in trace_diffs),
    )
