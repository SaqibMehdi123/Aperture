"""Cross-dispatch aggregator for live real-model arm runs (no network).

eval.live aggregates only what a single dispatch ran. The results tree,
however, is append-only and accumulates cells across dispatches and
providers (gap-fill retries, per-provider runs). This module re-aggregates
the merged tree from disk: for every (provider, arm, family) cell it takes
the latest COMPLETE run (a run-*.json that carries a summary block),
recomputes the per-cell aggregates from its per_seed rows, and emits the
same savings / G1 headline as eval.compare and eval.live - without
spending a single API token.

    python -m eval.compare_live [--arms a,b,c] [--families f,g,h]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aperture import __version__

from eval.harness import current_git_hash
from eval.live import DEFAULT_LIVE_ARMS, _aggregate, summarize_live
from eval.tasks import FAMILIES

LIVE_ROOT = Path(__file__).resolve().parents[1] / "results" / "live"
COMPARE_ROOT = Path(__file__).resolve().parents[1] / "results" / "compare"


def collect_cells(results_root: str | Path = LIVE_ROOT) -> list[dict[str, Any]]:
    """Parse every complete run in results/live/<family>/<arm>/run-*.json.

    Incomplete runs (no summary block - the crash-resilience artifacts) and
    malformed files are skipped; the provider comes from manifest.notes.
    """
    cells: list[dict[str, Any]] = []
    for path in sorted(Path(results_root).glob("*/*/run-*.json")):
        family, arm = path.parent.parent.name, path.parent.name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue  # truncated/malformed file; the .jsonl detail survives
        if "summary" not in payload or "per_seed" not in payload:
            continue  # incomplete run: never shadow a complete one
        manifest = payload.get("manifest", {})
        notes = manifest.get("notes") or {}
        if not notes.get("provider"):
            continue
        cells.append(
            {
                "provider": notes["provider"],
                "arm": arm,
                "family": family,
                "run_file": path.name,
                "started_at": manifest.get("started_at", ""),
                "model_string": notes.get("model_string", ""),
                "seeds": manifest.get("seeds", []),
                "aggregate": _aggregate(payload["per_seed"]),
            }
        )
    return cells


def pick_latest(cells: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Keep the newest complete run per (provider, arm, family) cell.

    Ordering key: manifest.started_at, then the stamped filename (both UTC,
    so lexicographic order is chronological).
    """
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for cell in cells:
        key = (cell["provider"], cell["arm"], cell["family"])
        cur = out.get(key)
        if cur is None or (cell["started_at"], cell["run_file"]) > (
            cur["started_at"],
            cur["run_file"],
        ):
            out[key] = cell
    return out


def _g1_live(
    table: dict[str, dict[str, dict[str, Any]]],
    arms: tuple[str, ...],
    families: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """G1 headline on real models: savings at equal-or-better success.

    Mirrors eval.compare's g1_rehearsal over whatever cells exist; arms
    with no data report None metrics and complete=False instead of lying.
    """
    out: dict[str, dict[str, Any]] = {}
    for arm in arms:
        if arm == "full_history":
            continue  # the baseline is never graded against itself
        fams = table.get(arm, {})
        have = [f for f in families if f in fams]
        savings = [fams[f]["savings_frac"] for f in have]
        parity = [fams[f]["success_equal_or_better"] for f in have]
        out[arm] = {
            "min_savings_frac": round(min(savings), 4) if savings else None,
            "success_equal_or_better": all(parity) if parity else None,
            "cells_with_data": len(have),
            "cells_expected": len(families),
            "complete": bool(fams) and len(have) == len(families),
        }
    return out


def _coverage(
    cells: dict[tuple[str, str, str], dict[str, Any]],
    provider: str,
    arms: tuple[str, ...],
    families: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Per-cell provenance: which run fed each cell, None if missing."""
    out: dict[str, dict[str, Any]] = {}
    for arm in arms:
        out[arm] = {}
        for family in families:
            cell = cells.get((provider, arm, family))
            out[arm][family] = (
                None
                if cell is None
                else {
                    "run_file": cell["run_file"],
                    "model_string": cell["model_string"],
                    "started_at": cell["started_at"],
                }
            )
    return out


def compare_live(
    results_root: str | Path = LIVE_ROOT,
    out_root: str | Path = COMPARE_ROOT,
    arms: tuple[str, ...] = DEFAULT_LIVE_ARMS,
    families: tuple[str, ...] = FAMILIES,
) -> dict[str, Any]:
    """Aggregate the merged live tree per provider; write an append-only summary."""
    cells = pick_latest(collect_cells(results_root))
    providers = sorted({c["provider"] for c in cells.values()})

    providers_summary: dict[str, Any] = {}
    for provider in providers:
        table: dict[str, dict[str, dict[str, Any]]] = {}
        for (prov, arm, family), cell in cells.items():
            if prov == provider:
                table.setdefault(arm, {})[family] = cell["aggregate"]
        providers_summary[provider] = {
            "arms": summarize_live(table),
            "g1_live": _g1_live(summarize_live(table), arms, families),
            "coverage": _coverage(cells, provider, arms, families),
        }

    summary = {
        "manifest": {
            "git_hash": current_git_hash(),
            "aperture_version": __version__,
            "source_tree": str(results_root),
            "providers": providers,
            "arms": list(arms),
            "families": list(families),
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "note": "aggregated from disk (latest complete run per cell); "
            "no network calls; partial grids flagged in g1_live/coverage",
        },
        "providers": providers_summary,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = Path(out_root) / f"live-summary-{stamp}.json"
    if out.exists():  # append-only guard
        raise RuntimeError(f"result collision: {out} exists")
    Path(out_root).mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["path"] = str(out)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate live arm results from disk")
    parser.add_argument("--arms", default=",".join(DEFAULT_LIVE_ARMS))
    parser.add_argument("--families", default=",".join(FAMILIES))
    args = parser.parse_args()
    arms = tuple(s.strip() for s in args.arms.split(",") if s.strip())
    families = tuple(s.strip() for s in args.families.split(",") if s.strip())

    summary = compare_live(arms=arms, families=families)
    for provider, prov in summary["providers"].items():
        g1 = prov["g1_live"]
        n_cells = sum(a["cells_with_data"] for a in g1.values())
        print(f"\n== {provider} ({n_cells}/{len(g1) * len(families)} non-baseline cells) ==")
        print("| arm | " + " | ".join(families) + " |")
        print("|---|" + "---|" * (len(families) + 1))
        for arm, fams in prov["arms"].items():
            row = []
            for family in families:
                agg = fams.get(family)
                row.append(
                    "-"
                    if agg is None
                    else f"{agg['input_tokens']:,} tok ({agg['savings_frac']:.0%}), "
                    f"acc {agg['success_rate']:.2f}"
                )
            print(f"| {arm} | " + " | ".join(row) + " |")
        for arm, g in g1.items():
            if g["cells_with_data"] == 0:
                continue
            savings = "-" if g["min_savings_frac"] is None else f"{g['min_savings_frac']:.0%}"
            parity = {True: "yes", False: "NO", None: "-"}[g["success_equal_or_better"]]
            flag = (
                "" if g["complete"] else f"  [PARTIAL {g['cells_with_data']}/{g['cells_expected']}]"
            )
            print(f"G1-live {arm}: min savings {savings}, success parity {parity}{flag}")
    print(f"\nmanifest: {summary['path']}")


if __name__ == "__main__":
    main()
