"""Offline arm comparison - the G1 rehearsal runner (spec Table 6 P2).

Runs every offline arm (eval/arms.py) over the deterministic task suite
(eval/tasks.py) with identical loops, stores, and grading, writes one
append-only result file per (benchmark, arm) via the shared harness, and
aggregates a summary with the G1-rehearsal check: savings at equal-or-better
task success, with 100% of curation decisions logged.

    python -m eval.compare
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aperture import __version__

from eval.arms import ARMS_OFFLINE, TUNED_BALANCED, make_aperture
from eval.harness import current_git_hash, run_arm
from eval.tasks import EVAL_SEEDS, FAMILIES, family_model, run_task

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results"


def _run_traced_task(arm: str, family: str, seed: int, model) -> dict:
    """One task with its own ledger; verifies every call left a trace line."""
    from aperture.trace.ledger import TraceLedger

    with tempfile.TemporaryDirectory(prefix="aperture-trace-") as td:
        ledger = TraceLedger(Path(td) / "trace.jsonl")
        ap = make_aperture(arm, model, ledger=ledger)
        stats = run_task(family, seed, ap)
        stats["trace_records"] = len(list(ledger.records()))
    return stats


def compare(
    arms: tuple[str, ...] = ARMS_OFFLINE,
    families: tuple[str, ...] = FAMILIES,
    seeds: tuple[int, ...] = EVAL_SEEDS,
    results_root: str | Path = RESULTS_ROOT,
) -> dict[str, Any]:
    """Run all arms x families x seeds; write append-only results + summary."""
    per_arm: dict[str, dict[str, Any]] = {}
    for family in families:
        model = family_model(family)
        for arm in arms:
            make_aperture(arm, model)  # fail fast on unknown arms

            def task_fn(m, seed, _arm=arm, _family=family, _model=model):
                return _run_traced_task(_arm, _family, seed, _model)

            payload = run_arm(
                arm,
                family,
                task_fn,
                lambda _model=model: _model,
                seeds=list(seeds),
                results_root=results_root,
            )
            rows = payload["per_seed"]
            agg = _aggregate(rows)
            per_arm.setdefault(arm, {})[family] = agg

    full = per_arm.get("full_history", {})
    table = {}
    for arm, fams in per_arm.items():
        table[arm] = {}
        for family, agg in fams.items():
            base = full.get(family, {}).get("input_tokens", 0)
            agg["savings_frac"] = round(1.0 - agg["input_tokens"] / base, 4) if base else 0.0
            table[arm][family] = agg

    g1 = {
        arm: {
            "min_savings_frac": round(min(f["savings_frac"] for f in fams.values()), 4),
            "success_equal_or_better": all(
                f["success_rate"] >= full.get(fam, {}).get("success_rate", 0.0) - 1e-9
                for fam, f in fams.items()
            ),
            "fully_traced": all(f["trace_coverage"] == 1.0 for f in fams.values()),
        }
        for arm, fams in table.items()
        if arm != "full_history"
    }

    summary = {
        "manifest": {
            "git_hash": current_git_hash(),
            "aperture_version": __version__,
            "arms": list(arms),
            "families": list(families),
            "seeds": list(seeds),
            "tuned_params": TUNED_BALANCED,
            "note": "deterministic offline suite (synthetic grading models); "
            "not a real-model benchmark - AppWorld/tau2 runs need an API key; "
            "needle_qa facts declared via chat.facts() DX API, P3-2 posture "
            "(mark_facts=True; pre-P3-2 loop = mark_facts=False)",
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        },
        "arms": table,
        "g1_rehearsal": g1,
    }

    out_dir = Path(results_root) / "compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = out_dir / f"summary-{stamp}.json"
    if out.exists():  # append-only guard
        raise RuntimeError(f"result collision: {out} exists")
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["path"] = str(out)
    return summary


def _aggregate(rows: list[dict]) -> dict:
    n = max(1, len(rows))
    calls = sum(r["calls"] for r in rows)
    hits = sum(r["cache_hits"] for r in rows)
    misses = sum(r["cache_misses"] for r in rows)
    traced = sum(r.get("trace_records", 0) for r in rows)
    return {
        "n_tasks": len(rows),
        "success_rate": round(sum(1 for r in rows if r["success"]) / n, 4),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "cache_hit_rate": round(hits / max(1, hits + misses), 4),
        "probes_failed": sum(r["probes_failed"] for r in rows),
        "calls": calls,
        "trace_coverage": round(traced / max(1, calls), 4),
    }


def main() -> None:
    summary = compare()
    fam_names = list(next(iter(summary["arms"].values())).keys())
    head = (
        "| arm | success | " + " | ".join(f"{f} tokens (saved)" for f in fam_names) + " | traced |"
    )
    print(head)
    print("|---|" + "---|" * (len(fam_names) + 2))
    for arm, fams in summary["arms"].items():
        succ = round(sum(f["success_rate"] for f in fams.values()) / len(fams), 3)
        cells = " | ".join(
            f"{f['input_tokens']:,} ({f['savings_frac']:.0%})" for f in fams.values()
        )
        cov = round(min(f["trace_coverage"] for f in fams.values()), 3)
        print(f"| {arm} | {succ} | {cells} | {cov} |")
    print(f"manifest: {summary['path']}")


if __name__ == "__main__":
    main()
