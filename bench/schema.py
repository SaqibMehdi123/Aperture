"""CurateBench trace schema v1 (dossier Appendix A).

One JSON Lines record per model call captures the full state needed to
reconstruct the step and to re-run it under a different curation policy: the
features the selector saw, the plan it chose, the diffs every operator
produced, the cache state, the survival probes, and the eventual task outcome
joined after the run completes.

The schema is versioned from Phase P0; any logged-field change bumps
SCHEMA_VERSION and the version string. Strict parsing (extra="forbid") keeps
the corpus and the benchmark seeds trustworthy.

Note on `reward`: the runtime Reward (spec 7.3) carries `cache_invalidation`
as a fifth field; in the trace it is derivable from `cache.invalidated_bytes`,
so the serialized reward keeps exactly the four Appendix A fields.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_ID = "curatebench/trace"
SCHEMA_VERSION = 1
SCHEMA_VERSIONED = f"{SCHEMA_ID}@v{SCHEMA_VERSION}"


class ModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    id: str
    price_list: str


class FeatureVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_used_frac: float
    task_phase: str
    tool_output_tokens_recent: int
    redundancy_score: float
    drift_score: float
    prefix_hash: str


class PlannedOpRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    params: dict[str, Any] = Field(default_factory=dict)
    order: int = 0


class DroppedSpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    bytes: int
    reason: str
    classes: list[str] = Field(default_factory=list)


class NewSpanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    bytes: int
    summary_of: list[str] = Field(default_factory=list)


class DiffRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: str
    dropped: list[DroppedSpanRecord] = Field(default_factory=list)
    new_spans: list[NewSpanRecord] = Field(default_factory=list)
    cache_head_unchanged: bool = True


class CacheState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix_tokens: int
    hit: bool
    invalidated_bytes: int
    discount_usd: float


class ProbeRecord(BaseModel):
    """`class` is a reserved word in Python; aliased in and out."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    probe_class: str = Field(alias="class")
    probe: str
    survived: bool


class CallStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class RewardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_progress: float
    cost_delta_usd: float
    survival_penalty: float
    latency_ms: float


class OutcomeRecord(BaseModel):
    """Task-level grade, joined after the run completes (may be absent)."""

    model_config = ConfigDict(extra="forbid")

    task_success: bool
    graded_at: str | None = None


class TraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_: str = Field(alias="schema")
    step: int
    ts: str
    session_id: str
    arm: str
    model: ModelInfo
    features: FeatureVector
    plan: list[PlannedOpRecord] = Field(default_factory=list)
    diffs: list[DiffRecord] = Field(default_factory=list)
    cache: CacheState
    probes: list[ProbeRecord] = Field(default_factory=list)
    call: CallStats
    reward: RewardRecord
    outcome: OutcomeRecord | None = None

    def dump_json(self) -> str:
        """Canonical JSONL line (alias names, Appendix A field order)."""
        return self.model_dump_json(by_alias=True)


def trace_schema_json() -> dict[str, Any]:
    """JSON Schema for the v1 trace record (benchmark artifact)."""
    schema = TraceRecord.model_json_schema()
    schema["$id"] = f"https://curatebench.dev/schemas/trace@v{SCHEMA_VERSION}"
    schema["title"] = "CurateBench trace record"
    return schema


# The Appendix A example, kept as the executable contract for tests and docs.
EXAMPLE_V1: dict[str, Any] = {
    "schema": "curatebench/trace@v1",
    "step": 47,
    "ts": "2027-03-14T09:22:11.408Z",
    "session_id": "appworld-train-0031",
    "arm": "aperture_learned",
    "model": {"provider": "anthropic", "id": "claude-sonnet-4-5", "price_list": "2027-03-01"},
    "features": {
        "budget_used_frac": 0.41,
        "task_phase": "explore",
        "tool_output_tokens_recent": 5210,
        "redundancy_score": 0.33,
        "drift_score": 0.07,
        "prefix_hash": "b3f1c9...e2a0",
    },
    "plan": [
        {"op": "dedupe", "params": {"sim_threshold": 0.93}, "order": 1},
        {"op": "summarize", "params": {"budget_tokens": 900}, "order": 2},
        {"op": "cache_align", "params": {"head_budget": 4096}, "order": 0},
    ],
    "diffs": [
        {
            "op": "summarize",
            "dropped": [
                {
                    "span_id": "s-318",
                    "bytes": 6412,
                    "reason": "verbose tool output folded",
                    "classes": ["tool_result"],
                }
            ],
            "new_spans": [{"span_id": "s-401", "bytes": 890, "summary_of": ["s-318", "s-319"]}],
            "cache_head_unchanged": True,
        }
    ],
    "cache": {
        "prefix_tokens": 18422,
        "hit": True,
        "invalidated_bytes": 0,
        "discount_usd": 0.0413,
    },
    "probes": [{"class": "constraint", "probe": "refund-policy-q3", "survived": True}],
    "call": {
        "input_tokens": 20087,
        "output_tokens": 412,
        "cost_usd": 0.0762,
        "latency_ms": 1841,
    },
    "reward": {
        "task_progress": 0.25,
        "cost_delta_usd": 0.0095,
        "survival_penalty": 0.0,
        "latency_ms": 122,
    },
    "outcome": {"task_success": True, "graded_at": "2027-03-14T09:31:02Z"},
}
