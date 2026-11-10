"""P2 arms + comparison runner."""

import json
from pathlib import Path

import pytest
from aperture.session import Features
from eval.arms import ARMS_OFFLINE, AlwaysCompress, ToolLoadTrim, make_aperture
from eval.compare import compare
from eval.tasks import FAMILIES, family_model


def _features(tool_load: float = 0.0, budget: float = 0.9) -> Features:
    return Features(
        budget_used_frac=budget,
        task_phase="act",
        tool_output_tokens_recent=tool_load,
        redundancy_score=0.0,
        drift_score=0.0,
        prefix_hash="p",
    )


def test_always_compress_plans_summarize_every_step():
    plan = AlwaysCompress().select(_features(budget=0.1))
    assert [p.op for p in plan] == ["summarize"]


def test_tool_load_trim_scales_with_recent_tool_load():
    assert ToolLoadTrim().select(_features(tool_load=900))[0].params == {"keep_n": 4}
    assert ToolLoadTrim().select(_features(tool_load=500))[0].params == {"keep_n": 8}
    assert ToolLoadTrim().select(_features(tool_load=100)) == []


def test_make_aperture_builds_every_offline_arm():
    model = family_model("needle_qa")
    for arm in ARMS_OFFLINE:
        ap = make_aperture(arm, model)
        assert ap.model is model
    with pytest.raises(ValueError):
        make_aperture("not_an_arm", model)


def test_full_history_arm_never_curates():
    from eval.tasks import run_task

    stats = run_task(
        "needle_qa", seed=5, make_ap=make_aperture("full_history", family_model("needle_qa"))
    )
    assert stats["success"]
    assert stats["spans_dropped"] == 0


def test_compare_end_to_end(tmp_path):
    summary = compare(
        arms=("full_history", "aperture_fixed"),
        families=FAMILIES[:1],
        seeds=(0, 1),
        results_root=tmp_path,
    )
    fam = FAMILIES[0]
    full = summary["arms"]["full_history"][fam]
    fixed = summary["arms"]["aperture_fixed"][fam]
    assert full["success_rate"] == 1.0
    assert fixed["success_rate"] == 1.0
    assert fixed["savings_frac"] > 0.1  # curation must actually save
    assert fixed["trace_coverage"] == 1.0  # G1: every decision logged
    g1 = summary["g1_rehearsal"]["aperture_fixed"]
    assert g1["success_equal_or_better"] and g1["fully_traced"]
    # append-only results written under the results tree
    assert list(Path(tmp_path).glob(f"{fam}/aperture_fixed/run-*.json"))
    out = json.loads(Path(summary["path"]).read_text())
    assert out["manifest"]["git_hash"]
