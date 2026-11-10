"""P0 eval probes: extended NIAH, focused-vs-full, ConstraintRot, harness."""

import json

import pytest
from eval.constraint_rot import constraint_rot_probe
from eval.context_rot import (
    focused_vs_full_probe,
    niah_probe,
    rot_monotone_decline,
    save_curve,
)
from eval.harness import ARMS, run_arm
from eval.probes import SyntheticComplianceModel, SyntheticProbeModel


def test_niah_curve_declines_with_length_and_depth():
    curve = niah_probe(
        model=SyntheticProbeModel(),
        lengths=(1000, 4000, 8000),
        depths=(0.1, 0.9),
        trials=2,
        seed=0,
    )
    assert len(curve.points) == 6
    assert rot_monotone_decline(curve)  # published direction reproduced
    easiest = min(curve.points, key=lambda p: p.filler_tokens * (0.5 + p.depth_frac))
    hardest = max(curve.points, key=lambda p: p.filler_tokens * (0.5 + p.depth_frac))
    assert easiest.accuracy > hardest.accuracy


def test_niah_saves_json(tmp_path):
    curve = niah_probe(model=SyntheticProbeModel(), lengths=(1000,), depths=(0.5,), trials=1)
    out = tmp_path / "curves" / "niah.json"
    save_curve(curve, out)
    data = json.loads(out.read_text())
    assert data["suite"] == "extended_niah"
    assert data["points"][0]["accuracy"] in (0.0, 1.0)


def test_focused_vs_full_token_savings():
    summary = focused_vs_full_probe(model=SyntheticProbeModel(), filler_tokens=4000)
    assert summary["tokens_focused"] < summary["tokens_full"]
    assert summary["token_savings_frac"] > 0.9
    assert summary["acc_focused"] >= summary["acc_full"]


def test_constraint_rot_directions():
    report = constraint_rot_probe(model=SyntheticComplianceModel(), trials=3)
    c = report["conditions"]
    assert c["none"]["violations"] == 0  # intact context -> compliant
    assert c["naive_truncate"]["violations"] == 3  # naive compaction drops the policy
    assert c["protected"]["violations"] == 0  # guardrail retains it
    assert report["protected_survival_rate"] == 1.0


def test_protected_condition_keeps_constraint_span():
    from aperture.engine import CurationEngine
    from aperture.interfaces import PlannedOp
    from eval.constraint_rot import NaiveTailTruncate, build_window, run_condition

    base = build_window(2000, seed=3, include_constraint=True, protected=True)
    engine = CurationEngine(registry={"naive_tail_truncate": NaiveTailTruncate()})
    composed, diffs = engine.compose(
        base,
        [PlannedOp(op="naive_tail_truncate", params={"keep_n": 1}, order=0)],
        _feats(base),
    )
    assert composed.find("c-0") is not None  # guardrail vetoed the drop
    assert "c-0" in diffs[0].probe_targets
    # and end to end:
    assert "cannot approve" in run_condition(
        SyntheticComplianceModel(), "protected", filler_tokens=2000
    )


def test_harness_runs_arm_and_writes_manifest(tmp_path):
    def task_fn(model, seed):
        return {"success": True, "cost_usd": 0.01 * seed, "tokens": 100}

    payload = run_arm(
        "aperture_fixed",
        "toy",
        task_fn,
        SyntheticComplianceModel,
        seeds=[1, 2],
        results_root=tmp_path,
        price_list="test-2026-11",
    )
    assert payload["summary"]["success_rate"] == 1.0
    assert payload["manifest"]["arm"] == "aperture_fixed"
    assert payload["manifest"]["benchmark"] == "toy"
    assert payload["manifest"]["seeds"] == [1, 2]
    assert payload["manifest"]["git_hash"]
    files = list((tmp_path / "toy" / "aperture_fixed").glob("run-*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text())
    assert on_disk["manifest"]["price_list"] == "test-2026-11"


def test_harness_is_append_only(tmp_path):
    task_fn = lambda model, seed: {"success": False, "cost_usd": 0.0, "tokens": 5}  # noqa: E731
    for _ in range(2):
        run_arm(
            "full_history", "toy", task_fn, SyntheticProbeModel, seeds=[1], results_root=tmp_path
        )
    files = list((tmp_path / "toy" / "full_history").glob("run-*.json"))
    assert len(files) == 2  # never overwritten


def test_harness_rejects_unknown_arm(tmp_path):
    with pytest.raises(ValueError):
        run_arm(
            "not_an_arm", "toy", lambda m, s: {}, SyntheticProbeModel,
            seeds=[1], results_root=tmp_path,
        )


def test_eight_arms_registered():
    assert len(ARMS) == 8
    assert "aperture_learned" in ARMS and "full_history" in ARMS


def _feats(w):
    from aperture.session import Features

    return Features(
        budget_used_frac=w.used_frac(), task_phase="act", tool_output_tokens_recent=0,
        redundancy_score=0.0, drift_score=0.0, prefix_hash=w.prefix_hash(),
    )
