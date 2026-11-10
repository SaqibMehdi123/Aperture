"""Eval harness: every arm runs under the same harness, seeds, and grading
(spec Section 9).

Every run writes a manifest (git hash, arm, benchmark, seeds, model IDs,
price list) into the results tree; the tree is append-only - results are
never overwritten, and unfavorable results are committed too (spec 8.3).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from aperture import __version__

# The eight arms (spec 9, "Arms"). Arm 4 is model-specific and reported
# separately; arms 5-6 carry the re-measurement caveat.
ARMS: tuple[str, ...] = (
    "full_history",
    "keep_recent_tuned",
    "threshold_edit_compact",
    "provider_native_anthropic",
    "acon_always_compress",
    "headroom_proxy",
    "aperture_fixed",
    "aperture_learned",
)

TaskFn = Callable[..., dict]  # task_fn(model, seed) -> {"success": bool, "cost_usd": float, ...}
ModelFactory = Callable[[], object]


@dataclass
class RunManifest:
    git_hash: str
    arm: str
    benchmark: str
    seeds: list[int]
    model_ids: list[str]
    price_list: str
    aperture_version: str
    started_at: str
    notes: dict = field(default_factory=dict)


def current_git_hash(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def run_arm(
    arm: str,
    benchmark: str,
    task_fn: TaskFn,
    model_factory: ModelFactory,
    seeds: list[int],
    results_root: str | Path = "results",
    model_ids: list[str] | None = None,
    price_list: str = "unarchived",
    notes: dict | None = None,
) -> dict:
    """Run one arm x benchmark across seeds; write an append-only result file.

    `task_fn(model, seed)` returns a dict with at least `success` (bool) and
    `cost_usd` (float); harness adds token fields when present. Returns the
    aggregated summary dict that was written to disk.
    """
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}; must be one of {ARMS}")

    model = model_factory()
    per_seed = []
    for seed in seeds:
        result = dict(task_fn(model, seed))
        result["seed"] = seed
        per_seed.append(result)

    n_success = sum(1 for r in per_seed if r.get("success"))
    total_cost = sum(float(r.get("cost_usd", 0.0)) for r in per_seed)
    total_tokens = sum(int(r.get("tokens", 0)) for r in per_seed)
    summary = {
        "success_rate": round(n_success / len(per_seed), 6) if per_seed else 0.0,
        "total_cost_usd": round(total_cost, 6),
        "total_tokens": total_tokens,
        "n_tasks": len(per_seed),
    }

    manifest = RunManifest(
        git_hash=current_git_hash(),
        arm=arm,
        benchmark=benchmark,
        seeds=list(seeds),
        model_ids=model_ids or [_model_id(model)],
        price_list=price_list,
        aperture_version=__version__,
        started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        notes=notes or {},
    )
    payload = {"manifest": asdict(manifest), "summary": summary, "per_seed": per_seed}

    out_dir = Path(results_root) / benchmark / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_path = out_dir / f"run-{stamp}.json"
    if out_path.exists():  # append-only guard: never overwrite a result
        raise RuntimeError(f"result collision: {out_path} exists; results are append-only")
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _model_id(model: object) -> str:
    describe = getattr(model, "describe", None)
    if callable(describe):
        _, model_id = describe()
        return model_id
    return type(model).__name__
