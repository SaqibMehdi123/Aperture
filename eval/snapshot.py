"""Snapshot the offline probe suites into the append-only results tree.

Runs the three deterministic probe suites (extended NIAH, focused-vs-full,
ConstraintRot) against the synthetic probe models - no network, no API keys -
and writes one manifest + data JSON per suite under ``results/probes/``.
Snapshots are append-only: an existing file is never overwritten.

Run:

    python -m eval.snapshot

These snapshots verify harness wiring and reproduce the published *direction*
of each failure mode (Chroma 2025; arXiv:2606.22528) at CI scale. They are not
benchmarks: real-model runs re-measure everything (spec Section 9) and land in
this tree from Phase P2 with the same manifest discipline.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aperture import __version__

from eval.constraint_rot import constraint_rot_probe
from eval.context_rot import focused_vs_full_probe, niah_probe, rot_monotone_decline
from eval.harness import current_git_hash
from eval.probes import SyntheticComplianceModel, SyntheticProbeModel

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results" / "probes"

_PURPOSE = "direction check on the synthetic model at CI scale; not a benchmark"


def _manifest(model_id: str, price_list: str, notes: dict[str, Any]) -> dict[str, Any]:
    return {
        "git_hash": current_git_hash(),
        "aperture_version": __version__,
        "model_ids": [model_id],
        "price_list": price_list,
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "notes": notes,
    }


def _write_append_only(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():  # append-only guard: never overwrite a result
        raise RuntimeError(f"result collision: {path} exists; results are append-only")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def snapshot_niah(seed: int = 0, results_root: str | Path = RESULTS_ROOT) -> Path:
    """Extended NIAH over the depth x length grid on the synthetic rot model."""
    model = SyntheticProbeModel()
    curve = niah_probe(model=model, seed=seed)
    load = lambda p: p.filler_tokens * (0.5 + p.depth_frac)  # noqa: E731
    easiest, hardest = min(curve.points, key=load), max(curve.points, key=load)
    payload = {
        "manifest": _manifest(
            curve.model_id, model.price_list, {"purpose": _PURPOSE, "seed": seed}
        ),
        "summary": {
            "grid_points": len(curve.points),
            "acc_easiest": easiest.accuracy,
            "acc_hardest": hardest.accuracy,
            "monotone_decline_direction": rot_monotone_decline(curve),
        },
        "data": asdict(curve),
    }
    out = Path(results_root) / "extended_niah" / f"snapshot-{_stamp()}.json"
    _write_append_only(out, payload)
    return out


def snapshot_focused_vs_full(seed: int = 7, results_root: str | Path = RESULTS_ROOT) -> Path:
    """LongMemEval-style focused-vs-full on the synthetic rot model."""
    model = SyntheticProbeModel()
    result = focused_vs_full_probe(model=model, seed=seed)
    payload = {
        "manifest": _manifest(
            result["model_id"], model.price_list, {"purpose": _PURPOSE, "seed": seed}
        ),
        "summary": {
            "acc_full": result["acc_full"],
            "acc_focused": result["acc_focused"],
            "token_savings_frac": result["token_savings_frac"],
        },
        "data": result,
    }
    out = Path(results_root) / "focused_vs_full" / f"snapshot-{_stamp()}.json"
    _write_append_only(out, payload)
    return out


def snapshot_constraint_rot(
    trials: int = 5, seed: int = 3, results_root: str | Path = RESULTS_ROOT
) -> Path:
    """ConstraintRot three-condition run on the synthetic compliance model."""
    model = SyntheticComplianceModel()
    result = constraint_rot_probe(model=model, trials=trials, seed=seed)
    conditions = result["conditions"]
    payload = {
        "manifest": _manifest(
            result["model_id"], model.price_list, {"purpose": _PURPOSE, "seed": seed}
        ),
        "summary": {
            "violation_rate_none": conditions["none"]["violation_rate"],
            "violation_rate_naive_truncate": conditions["naive_truncate"]["violation_rate"],
            "violation_rate_protected": conditions["protected"]["violation_rate"],
            "protected_survival_rate": result["protected_survival_rate"],
        },
        "data": result,
    }
    out = Path(results_root) / "constraint_rot" / f"snapshot-{_stamp()}.json"
    _write_append_only(out, payload)
    return out


def main(results_root: str | Path = RESULTS_ROOT) -> None:
    for snapshot in (snapshot_niah, snapshot_focused_vs_full, snapshot_constraint_rot):
        print(f"wrote {snapshot(results_root=results_root)}")


if __name__ == "__main__":
    main()
