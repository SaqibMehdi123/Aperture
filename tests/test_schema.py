"""CurateBench trace schema v1 (dossier Appendix A) - the versioned contract."""

import json

import pytest
from bench.schema import EXAMPLE_V1, SCHEMA_VERSIONED, TraceRecord, trace_schema_json
from pydantic import ValidationError


def test_appendix_a_example_parses():
    rec = TraceRecord.model_validate(EXAMPLE_V1)
    assert rec.schema_ == "curatebench/trace@v1"
    assert rec.step == 47
    assert rec.session_id == "appworld-train-0031"
    assert rec.arm == "aperture_learned"
    assert [p.op for p in rec.plan] == ["dedupe", "summarize", "cache_align"]
    assert rec.diffs[0].dropped[0].span_id == "s-318"
    assert rec.cache.hit is True
    assert rec.probes[0].probe_class == "constraint"  # aliased from "class"
    assert rec.outcome.task_success is True


def test_dump_json_uses_appendix_a_names():
    rec = TraceRecord.model_validate(EXAMPLE_V1)
    line = rec.dump_json()
    data = json.loads(line)
    assert data["schema"] == "curatebench/trace@v1"
    assert data["probes"][0]["class"] == "constraint"
    # 4-field reward per Appendix A (no cache_invalidation in the trace)
    assert set(data["reward"]) == {
        "task_progress",
        "cost_delta_usd",
        "survival_penalty",
        "latency_ms",
    }


def test_round_trip_is_lossless():
    rec = TraceRecord.model_validate(EXAMPLE_V1)
    again = TraceRecord.model_validate_json(rec.dump_json())
    assert again.model_dump(by_alias=True) == rec.model_dump(by_alias=True)


def test_strict_parsing_rejects_unknown_fields():
    bad = dict(EXAMPLE_V1)
    bad["surprise_field"] = 1
    with pytest.raises(ValidationError):
        TraceRecord.model_validate(bad)


def test_schema_version_string_is_frozen():
    # v2 (P1): additive diffs[].pinned[]; version bumped per the schema rule.
    assert SCHEMA_VERSIONED == "curatebench/trace@v2"


def test_json_schema_export():
    schema = trace_schema_json()
    assert schema["$id"].endswith("trace@v2")
    assert "TraceRecord" in schema["title"] or "trace" in schema["title"].lower()
    props = schema["properties"]
    for group in (
        "schema",
        "step",
        "features",
        "plan",
        "diffs",
        "cache",
        "probes",
        "call",
        "reward",
        "outcome",
    ):
        assert group in props
