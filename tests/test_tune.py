"""P2 tuner: constraint satisfaction, savings objective, append-only output."""

import json
from pathlib import Path

import pytest
from eval.tasks import FAMILIES
from eval.tune import GRID, score_config, tune


def test_grid_covers_the_three_knobs():
    assert len(GRID) == 48
    thresholds = {p["threshold"] for p in GRID}
    keep_ns = {p["keep_n"] for p in GRID}
    dedupes = {p["dedupe_at"] for p in GRID}
    assert thresholds == {0.5, 0.6, 0.7, 0.8}
    assert keep_ns == {6, 10, 14, 20}
    assert dedupes == {0.2, 0.4, 1.1}


def test_score_config_never_curates_config_has_most_tokens():
    off = score_config({"threshold": 1.01, "keep_n": 20, "dedupe_at": 1.1}, FAMILIES[:1], (200,))
    curating = score_config(
        {"threshold": 0.5, "keep_n": 10, "dedupe_at": 0.4}, FAMILIES[:1], (200,)
    )
    assert off["success_rate"] == 1.0  # never curating still answers
    assert curating["input_tokens"] < off["input_tokens"]


def test_tune_picks_feasible_config_and_writes_manifest(tmp_path):
    small_grid = (
        {"threshold": 1.01, "keep_n": 20, "dedupe_at": 1.1},  # off: max tokens
        {"threshold": 0.6, "keep_n": 10, "dedupe_at": 0.4},  # curating
        {"threshold": 0.5, "keep_n": 6, "dedupe_at": 0.2},  # aggressive
    )
    payload = tune(families=FAMILIES[:2], seeds=(201, 202), grid=small_grid, results_root=tmp_path)
    best = payload["best"]
    assert best["success_rate"] == 1.0
    assert best["probes_failed"] == 0
    assert best["params"]["threshold"] < 1.01  # never picks the no-curation config
    out = json.loads(Path(payload["path"]).read_text())
    assert out["manifest"]["git_hash"]
    assert out["manifest"]["grid_size"] == 3
    assert len(out["rows"]) == 3
    files = list(tmp_path.glob("run-*.json"))
    assert len(files) == 1


def test_tune_raises_when_constraints_unreachable(tmp_path, monkeypatch):
    """Defensive guard: an all-infeasible grid must raise, not ship a winner."""
    import eval.tune as tune_mod

    def infeasible(params, families, seeds):
        return {
            "params": dict(params),
            "tasks": 1,
            "success_rate": 0.5,
            "probes_failed": 3,
            "input_tokens": 10,
        }

    monkeypatch.setattr(tune_mod, "score_config", infeasible)
    with pytest.raises(RuntimeError):
        tune(families=FAMILIES[:1], seeds=(203,), results_root=tmp_path)
