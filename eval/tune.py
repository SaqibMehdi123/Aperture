"""Offline selector tuner (spec Table 6 P2: "tuned fixed-heuristic selector").

Grid-searches the `HeuristicSelector` knobs (threshold, keep_n, dedupe_at)
against the deterministic task suite (`eval/tasks.py`, TRAIN_SEEDS) under two
hard constraints - zero task failures and zero probe failures - and picks the
parameter set with the lowest cumulative input tokens. The winner is what
`PROFILES["balanced"]` ships; the sweep is reproducible with one command and
writes an append-only manifest into `results/tuning/` (spec 8.3 hygiene).

    python -m eval.tune
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aperture import __version__
from aperture.policy.fallback import HeuristicSelector

from eval.harness import current_git_hash
from eval.tasks import FAMILIES, TRAIN_SEEDS, family_model, run_task

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results" / "tuning"

GRID: tuple[dict, ...] = tuple(
    {"threshold": t, "keep_n": k, "dedupe_at": d}
    for t in (0.5, 0.6, 0.7, 0.8)
    for k in (6, 10, 14, 20)
    for d in (0.2, 0.4, 1.1)
)


def score_config(params: dict, families: tuple[str, ...], seeds: tuple[int, ...]) -> dict[str, Any]:
    """Run the suite under one parameter set; return the tuning objective."""
    from aperture import Aperture

    successes = 0
    n_tasks = 0
    input_tokens = 0
    probes_failed = 0
    for family in families:
        model = family_model(family)
        for seed in seeds:
            ap = Aperture(model=model, selector=HeuristicSelector(**params))
            stats = run_task(family, seed, ap)
            n_tasks += 1
            successes += int(stats["success"])
            input_tokens += stats["input_tokens"]
            probes_failed += stats["probes_failed"]
    return {
        "params": dict(params),
        "tasks": n_tasks,
        "success_rate": round(successes / max(1, n_tasks), 4),
        "probes_failed": probes_failed,
        "input_tokens": input_tokens,
    }


def tune(
    families: tuple[str, ...] = FAMILIES,
    seeds: tuple[int, ...] = TRAIN_SEEDS,
    grid: tuple[dict, ...] = GRID,
    results_root: str | Path = RESULTS_ROOT,
) -> dict:
    """Sweep the grid; return the winning summary (append-only file written)."""
    rows = [score_config(params, families, seeds) for params in grid]
    feasible = [r for r in rows if r["success_rate"] == 1.0 and r["probes_failed"] == 0]
    if not feasible:
        raise RuntimeError("no parameter set passes the task/probe constraints; widen the grid")
    best = min(feasible, key=lambda r: (r["input_tokens"], -r["params"]["threshold"]))

    payload = {
        "manifest": {
            "git_hash": current_git_hash(),
            "aperture_version": __version__,
            "families": list(families),
            "seeds": list(seeds),
            "grid_size": len(grid),
            "constraints": {"success_rate": 1.0, "probes_failed": 0},
            "objective": "min cumulative input tokens at equal task success",
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        },
        "best": best,
        "rows": rows,
    }
    out_dir = Path(results_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = out_dir / f"run-{stamp}.json"
    if out.exists():  # append-only guard
        raise RuntimeError(f"result collision: {out} exists")
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["path"] = str(out)
    return payload


def main() -> None:
    payload = tune()
    b = payload["best"]
    print(f"tuned: {b['params']}  ->  {b['input_tokens']} tokens, success {b['success_rate']}")
    print(f"manifest: {payload['path']}")


if __name__ == "__main__":
    main()
