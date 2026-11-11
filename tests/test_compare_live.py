"""Tests for the cross-dispatch live-results aggregator (eval/compare_live).

The aggregator reads the append-only results/live tree from disk (no
network, no tokens) and must: pick the latest COMPLETE run per cell,
aggregate from per_seed rows, compute savings/G1 vs full_history per
provider, flag partial grids, and write append-only summaries.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.compare_live import collect_cells, compare_live, pick_latest

ARMS = ("full_history", "keep_recent_tuned", "aperture_fixed")
FAMILIES = ("needle_qa", "policy_compliance", "aggregate_batch")


def _write_run(
    root: Path,
    provider: str,
    arm: str,
    family: str,
    stamp: str,
    started_at: str,
    input_tokens: int,
    output_tokens: int = 100,
    success: bool = True,
    with_summary: bool = True,
    model: str = "openai/test-model",
) -> None:
    """One synthetic run-<stamp>.json in the results/live tree layout."""
    d = Path(root) / "live" / family / arm
    d.mkdir(parents=True, exist_ok=True)
    row = {
        "seed": 0,
        "family": family,
        "success": success,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "calls": 4,
        "cache_hits": 0,
        "cache_misses": 4,
        "probes_failed": 0,
        "cost_usd": 0.0,
        "tokens": input_tokens + output_tokens,
        "bytes_dropped": 0,
        "spans_dropped": 0,
    }
    payload = {
        "manifest": {
            "arm": arm,
            "benchmark": family,
            "seeds": [0],
            "started_at": started_at,
            "model_ids": [model],
            "notes": {"provider": provider, "model_string": model},
        },
        "per_seed": [row],
    }
    if with_summary:
        payload["summary"] = {
            "n_tasks": 1,
            "success_rate": 1.0 if success else 0.0,
            "total_tokens": input_tokens + output_tokens,
            "total_cost_usd": 0.0,
        }
    (d / f"run-{stamp}.json").write_text(json.dumps(payload), encoding="utf-8")


def _full_grid(root: Path, provider: str, base: int, arm_tokens: int, success: bool = True):
    """full_history + aperture_fixed across all three families (provider-unique stamps)."""
    for i, fam in enumerate(FAMILIES):
        tag = f"20261110T150{i}00.000{provider}Z"
        _write_run(root, provider, "full_history", fam, tag,
                   f"2026-11-10T15:0{i}:00+00:00", input_tokens=base)
        _write_run(root, provider, "aperture_fixed", fam,
                   f"20261110T160{i}00.000{provider}Z",
                   f"2026-11-10T16:0{i}:00+00:00",
                   input_tokens=arm_tokens, success=success)


def test_latest_complete_run_wins(tmp_path):
    _write_run(tmp_path, "gemini", "full_history", "needle_qa",
               "20261110T150000.000000Z", "2026-11-10T15:00:00+00:00", input_tokens=10_000)
    _write_run(tmp_path, "gemini", "full_history", "needle_qa",
               "20261110T160000.000000Z", "2026-11-10T16:00:00+00:00", input_tokens=8_000)
    cells = pick_latest(collect_cells(tmp_path / "live"))
    cell = cells[("gemini", "full_history", "needle_qa")]
    assert cell["aggregate"]["input_tokens"] == 8_000


def test_incomplete_run_does_not_shadow_complete_one(tmp_path):
    _write_run(tmp_path, "gemini", "full_history", "needle_qa",
               "20261110T150000.000000Z", "2026-11-10T15:00:00+00:00", input_tokens=10_000)
    # newer but partial (crash mid-run): no summary block -> must be ignored
    _write_run(tmp_path, "gemini", "full_history", "needle_qa",
               "20261110T170000.000000Z", "2026-11-10T17:00:00+00:00",
               input_tokens=99_999, with_summary=False)
    cells = pick_latest(collect_cells(tmp_path / "live"))
    assert cells[("gemini", "full_history", "needle_qa")]["aggregate"]["input_tokens"] == 10_000


def test_malformed_run_file_skipped(tmp_path):
    bad = tmp_path / "live" / "needle_qa" / "aperture_fixed"
    bad.mkdir(parents=True)
    (bad / "run-garbage.json").write_text("{not json", encoding="utf-8")
    _write_run(tmp_path, "gemini", "full_history", "needle_qa",
               "20261110T150000.000000Z", "2026-11-10T15:00:00+00:00", input_tokens=10_000)
    cells = pick_latest(collect_cells(tmp_path / "live"))
    assert ("gemini", "full_history", "needle_qa") in cells
    assert ("gemini", "aperture_fixed", "needle_qa") not in cells


def test_savings_g1_full_grid(tmp_path):
    _full_grid(tmp_path, "gemini", base=10_000, arm_tokens=6_000)
    summary = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    prov = summary["providers"]["gemini"]
    row = prov["arms"]["aperture_fixed"]["needle_qa"]
    assert row["savings_frac"] == 0.4
    assert row["success_equal_or_better"] is True
    g1 = prov["g1_live"]["aperture_fixed"]
    assert g1["min_savings_frac"] == 0.4
    assert g1["success_equal_or_better"] is True
    assert g1["cells_with_data"] == 3
    assert g1["complete"] is True
    # the baseline arm itself is never graded against itself
    assert "full_history" not in prov["g1_live"]


def test_partial_grid_flagged(tmp_path):
    for fam in FAMILIES:
        _write_run(tmp_path, "gemini", "full_history", fam,
                   f"20261110T1500{FAMILIES.index(fam)}00.000000Z",
                   f"2026-11-10T15:0{FAMILIES.index(fam)}:00+00:00", input_tokens=10_000)
    # aperture_fixed only ran two of three families (crash mid-dispatch)
    for fam in FAMILIES[:2]:
        _write_run(tmp_path, "gemini", "aperture_fixed", fam,
                   f"20261110T1600{FAMILIES.index(fam)}00.000000Z",
                   f"2026-11-10T16:0{FAMILIES.index(fam)}:00+00:00", input_tokens=6_000)
    summary = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    g1 = summary["providers"]["gemini"]["g1_live"]["aperture_fixed"]
    assert g1["cells_with_data"] == 2
    assert g1["cells_expected"] == 3
    assert g1["complete"] is False
    # savings still computed over the cells that exist
    gem = summary["providers"]["gemini"]["arms"]["aperture_fixed"]
    assert gem["needle_qa"]["savings_frac"] == 0.4
    assert "aggregate_batch" not in gem


def test_no_data_arm_reported_as_incomplete(tmp_path):
    _full_grid(tmp_path, "gemini", base=10_000, arm_tokens=6_000)
    # keep_recent_tuned never ran: cells_with_data 0, complete False, no metrics
    summary = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    g1 = summary["providers"]["gemini"]["g1_live"]["keep_recent_tuned"]
    assert g1["cells_with_data"] == 0
    assert g1["complete"] is False
    assert g1["min_savings_frac"] is None
    assert g1["success_equal_or_better"] is None


def test_provider_grouping(tmp_path):
    _full_grid(tmp_path, "gemini", base=10_000, arm_tokens=6_000)
    _full_grid(tmp_path, "groq", base=20_000, arm_tokens=5_000)
    summary = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    assert set(summary["providers"]) == {"gemini", "groq"}
    gem = summary["providers"]["gemini"]["arms"]["aperture_fixed"]["needle_qa"]["savings_frac"]
    gro = summary["providers"]["groq"]["arms"]["aperture_fixed"]["needle_qa"]["savings_frac"]
    assert gem == 0.4  # 1 - 6000/10000 against the GEMINI baseline
    assert gro == 0.75  # 1 - 5000/20000 against the GROQ baseline


def test_append_only_summary_files(tmp_path):
    _full_grid(tmp_path, "gemini", base=10_000, arm_tokens=6_000)
    s1 = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    s2 = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    assert s1["path"] != s2["path"]
    assert Path(s1["path"]).exists() and Path(s2["path"]).exists()
    assert "g1_live" in s2["providers"]["gemini"]


def test_failing_task_lowers_success_and_parity(tmp_path):
    for i, fam in enumerate(FAMILIES):
        _write_run(tmp_path, "gemini", "full_history", fam,
                   f"20261110T1500{i}00.000000Z",
                   f"2026-11-10T15:0{i}:00+00:00",
                   input_tokens=10_000, success=True)
        _write_run(tmp_path, "gemini", "aperture_fixed", fam,
                   f"20261110T1600{i}00.000000Z",
                   f"2026-11-10T16:0{i}:00+00:00",
                   input_tokens=6_000, success=False)
    summary = compare_live(results_root=tmp_path / "live", out_root=tmp_path / "compare")
    g1 = summary["providers"]["gemini"]["g1_live"]["aperture_fixed"]
    assert g1["success_equal_or_better"] is False
