"""Live real-model arm runs - the P2 real-model half (spec Table 6 P2).

Same uniform loop, same arms, same append-only results tree as the offline
comparison (eval.compare) - but the deterministic grading models are replaced
by a real provider gateway. Everything is measured, nothing is copied.

    GROQ_API_KEY=...    python -m eval.live --provider groq
    GEMINI_API_KEY=...  python -m eval.live --provider gemini --seeds 0 \
        --arms full_history,aperture_fixed

Grading is tolerant to phrasing (a real model may answer "The access code is
1234." where the synthetic model answers "1234"); the graded quantity is
unchanged: exact value, exact sum, compliant refusal. The default subset
(3 arms x 3 families x 2 seeds ~= 18 tasks, a few hundred completions) fits
comfortably inside the Groq free tier and a smaller Gemini dispatch fits
inside its tighter free limits. Every call goes out with litellm retries on
429s.

Results land in results/live/<family>/<arm>/run-<stamp>.json plus a stamped
summary with the G1 headline (token savings at equal-or-better success vs
full-history, now measured on a real model). The network path only runs
under `python -m`; importing this module stays offline-safe.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eval.arms import make_aperture
from eval.harness import RunManifest, current_git_hash
from eval.provider_smoke import (
    API_KEY_ENV,
    PREFERRED,
    _list_models,
    gateway_route,
    pick_models,
)
from eval.tasks import EVAL_SEEDS, FAMILIES, run_task

RESULTS_ROOT = Path(__file__).resolve().parents[1] / "results" / "live"

DEFAULT_LIVE_ARMS: tuple[str, ...] = ("full_history", "keep_recent_tuned", "aperture_fixed")
DEFAULT_TOKEN_BUDGET = 150_000  # qwen free tier: 200k tokens/day

# Grader v3 vocabulary. v2 (3bc5f97) added denied/declined/refused; v3 adds
# imperative/verb-form denials ("Deny Refund.") and negated approvals, after
# the 2026-11-12 Groq re-grade showed a substantively correct baseline denial
# ("**Deny Refund.** ... the refund must not be approved.") failing on both
# patterns: "deny" was not in the vocabulary, and the `approved.?$` tail rule
# matched the *negated* ending. The tail rule now carries fixed-width
# negative lookbehinds so "(must|is|are) not be approved" and "never
# approved" endings are not read as approvals.
_REFUSAL_RE = re.compile(
    r"cannot (?:be )?approv"
    r"|can'?t (?:be )?approv"
    r"|unable to (?:be )?approv"
    r"|will not (?:be )?approv"
    r"|not (?:be )?approv"
    r"|must (?:be )?refus"
    r"|\bdeny\b"
    r"|\bdenies\b"
    r"|\bdenying\b"
    r"|\bdenied\b"
    r"|\bdeclined\b"
    r"|\brefused\b",
    re.IGNORECASE,
)
_APPROVAL_RE = re.compile(
    r"(has been|is|was) approved"
    r"|(?<!not )(?<!not be )(?<!never )approved\.?$",
    re.IGNORECASE,
)
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")


RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# proactive per-call pacing by provider: the cheapest way to live with a
# requests-per-minute cap is to never hit it
MIN_CALL_INTERVAL_S: dict[str, float] = {
    "groq": 1.0,  # 30 RPM
    "gemini": 15.0,  # ~4 RPM on the free tier
}


def is_retryable(exc: Exception) -> bool:
    """Whether a provider exception is transient: throttling (429) or a 5xx
    blip. Non-retryable failures (auth, region, missing model) surface
    immediately."""
    if getattr(exc, "status_code", None) in RETRYABLE_STATUS:
        return True
    name = type(exc).__name__
    return any(k in name for k in ("RateLimit", "ServiceUnavailable", "InternalServerError"))


def is_rate_limit(exc: Exception) -> bool:
    """Backward-compatible alias: 429-style throttling only."""
    if getattr(exc, "status_code", None) == 429:
        return True
    return "RateLimit" in type(exc).__name__


class RetryingGateway:
    """ModelGateway wrapper that paces calls and backs off transient errors.

    Free tiers cap requests-per-minute and tokens-per-day. Proactive pacing
    (`min_interval_s`) keeps RPM caps from ever tripping; reactive exponential
    backoff (attempts x base_s doubling) handles 429/5xx stragglers. litellm's
    own retry path needs tenacity, which we do not ship.
    """

    def __init__(
        self,
        inner,
        attempts: int = 6,
        base_s: float = 5.0,
        min_interval_s: float = 0.0,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self._inner = inner
        self._attempts = attempts
        self._base_s = base_s
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    def describe(self) -> tuple[str, str]:
        return self._inner.describe()

    @property
    def price_list(self) -> str:
        return getattr(self._inner, "price_list", "unarchived")

    def complete(self, window):
        # enforce a minimum gap between call starts (request-arrival pacing)
        if self._last_call is not None:
            wait = self._min_interval_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()
        for attempt in range(self._attempts):
            try:
                return self._inner.complete(window)
            except Exception as exc:
                if not is_retryable(exc) or attempt == self._attempts - 1:
                    raise
                backoff = self._base_s * (2**attempt)
                print(
                    f"[retry] transient provider error ({type(exc).__name__}); "
                    f"backing off {backoff:.0f}s (attempt {attempt + 1}/{self._attempts})"
                )
                self._sleep(backoff)


def grade_live(family: str, plan, reply: str) -> bool:
    """Tolerant grading for real models: same quantities as eval.tasks.grade,
    but robust to phrasing ("The access code is 1234." still passes)."""
    text = reply.strip()
    if family == "needle_qa":
        return re.search(rf"\b{re.escape(plan.expected)}\b", text) is not None
    if family == "aggregate_batch":
        target = float(plan.expected)
        return any(abs(float(x) - target) < 0.05 for x in _FLOAT_RE.findall(text))
    if family == "policy_compliance":
        return bool(_REFUSAL_RE.search(text)) and not bool(_APPROVAL_RE.search(text))
    raise ValueError(f"unknown family {family!r}")


def plan_matrix(arms: tuple[str, ...], families: tuple[str, ...], seeds: tuple[int, ...]):
    """Deterministic execution order: family -> arm -> seed."""
    return [(f, a, s) for f in families for a in arms for s in seeds]


def summarize_live(table: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Add savings_frac + success parity vs full_history per (arm, family).

    `table` maps arm -> family -> {"success_rate": float, "input_tokens": int}.
    """
    full = table.get("full_history", {})
    out: dict[str, dict[str, Any]] = {}
    for arm, fams in table.items():
        out[arm] = {}
        for family, agg in fams.items():
            base = full.get(family, {}).get("input_tokens", 0)
            row = dict(agg)
            row["savings_frac"] = round(1.0 - agg["input_tokens"] / base, 4) if base else 0.0
            row["success_equal_or_better"] = (
                agg["success_rate"] >= full.get(family, {}).get("success_rate", 1.0) - 1e-9
                if base
                else False
            )
            out[arm][family] = row
    return out


def resolve_gateway(provider: str, model: str | None, api_key: str):
    """Pick a model from the key's catalog (unless overridden), verify it with
    one tiny completion, and build the Aperture gateway for it.

    Returns (gateway, model_id, model_string, price_list).
    """
    from aperture.models.litellm_gateway import LiteLLMGateway

    from eval.provider_smoke import verify_model

    if model:
        model_id = model
    else:
        models = _list_models(provider, api_key)
        candidates = pick_models(models, PREFERRED[provider])
        print(f"[live] catalog candidates: {candidates}")
        model_id = verify_model(provider, api_key, candidates)
        if model_id is None:
            raise RuntimeError(f"no working chat model in the {provider} catalog")
    model_string, extra = gateway_route(provider, model_id)
    gateway = LiteLLMGateway(model_string, api_key=api_key, timeout_s=90.0, **extra)
    return gateway, model_id, model_string, f"{provider}-free-tier"


def _run_arm_live(
    arm: str,
    family: str,
    seeds: list[int],
    model,
    results_root: str | Path,
    price_list: str,
    notes: dict,
    budget: int,
    spent: dict,
    pause_s: float = 2.0,
) -> dict:
    """One arm x family against a live provider, crash-resilient.

    Every finished task is flushed to an append-only .jsonl immediately, so a
    provider-side death (e.g. the free tier's daily token cap) preserves all
    completed tasks. The canonical run-<stamp>.json payload is written at the
    end like the offline harness. `spent["tokens"]` accumulates across arms;
    once it reaches `budget` the remaining seeds are skipped and the manifest
    records `budget_capped`.
    """
    from dataclasses import asdict

    from aperture import __version__

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out_dir = Path(results_root) / family / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"run-{stamp}.jsonl"
    rows: list[dict] = []
    with jsonl_path.open("a", encoding="utf-8") as fh:
        for seed in seeds:
            if spent["tokens"] >= budget:
                notes["budget_capped"] = True
                break
            stats = dict(run_task(family, seed, make_aperture(arm, model), grader=grade_live))
            stats["seed"] = seed
            rows.append(stats)
            spent["tokens"] += int(stats["input_tokens"])
            fh.write(json.dumps(stats, sort_keys=True) + "\n")
            fh.flush()
            if pause_s > 0:
                time.sleep(pause_s)

    n_success = sum(1 for r in rows if r["success"])
    manifest = RunManifest(
        git_hash=current_git_hash(),
        arm=arm,
        benchmark=family,
        seeds=[r["seed"] for r in rows],
        model_ids=[_model_id(model)],
        price_list=price_list,
        aperture_version=__version__,
        started_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        notes=notes,
    )
    payload = {
        "manifest": asdict(manifest),
        "summary": {
            "n_tasks": len(rows),
            "success_rate": round(n_success / len(rows), 6) if rows else 0.0,
            "total_tokens": sum(int(r["input_tokens"]) for r in rows),
            "total_cost_usd": round(sum(float(r["cost_usd"]) for r in rows), 6),
        },
        "per_seed": rows,
    }
    json_path = jsonl_path.with_suffix(".json")
    if json_path.exists():  # append-only guard
        raise RuntimeError(f"result collision: {json_path} exists")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["path"] = str(jsonl_path)
    return payload


def _model_id(model: object) -> str:
    describe = getattr(model, "describe", None)
    if callable(describe):
        _, model_id = describe()
        return model_id
    return type(model).__name__


def live_compare(
    provider: str,
    arms: tuple[str, ...] = DEFAULT_LIVE_ARMS,
    families: tuple[str, ...] = FAMILIES,
    seeds: tuple[int, ...] = EVAL_SEEDS[:2],
    model: str | None = None,
    results_root: str | Path = RESULTS_ROOT,
    pause_s: float = 2.0,
    max_input_tokens: int = DEFAULT_TOKEN_BUDGET,
) -> dict[str, Any]:
    """Run arms x families x seeds against a real provider; write results.

    Stops early (gracefully, with a budget_capped summary) once the run's
    cumulative input tokens reach `max_input_tokens` - free tiers carry a
    daily token cap, and a capped-but-complete summary beats a dead job.
    """
    api_key = _require_key(provider)
    inner, model_id, model_string, price_list = resolve_gateway(provider, model, api_key)
    gateway = RetryingGateway(
        inner,
        attempts=7,
        base_s=10.0,
        min_interval_s=MIN_CALL_INTERVAL_S.get(provider, 1.0),
    )
    print(f"[live] provider={provider} model={model_id} price_list={price_list}")

    notes = {
        "provider": provider,
        "model_string": model_string,
        "grader": "grade_live v3 (imperative deny + negated approvals)",
        "suite": "deterministic task suite, real gateway",
    }
    per_arm: dict[str, dict[str, dict[str, Any]]] = {}
    matrix = plan_matrix(arms, families, seeds)
    spent = {"tokens": 0}
    for family in families:
        for arm in arms:
            arm_seeds = [s for f, a, s in matrix if f == family and a == arm]
            payload = _run_arm_live(
                arm,
                family,
                arm_seeds,
                gateway,
                results_root,
                price_list,
                notes,
                budget=max_input_tokens,
                spent=spent,
                pause_s=pause_s,
            )
            rows = payload["per_seed"]
            per_arm.setdefault(arm, {})[family] = _aggregate(rows)

    summary = {
        "manifest": {
            "git_hash": current_git_hash(),
            "provider": provider,
            "model_id": model_id,
            "price_list": price_list,
            "arms": list(arms),
            "families": list(families),
            "seeds": list(seeds),
            "grader": "grade_live v3 (imperative deny + negated approvals)",
            "input_token_budget": max_input_tokens,
            "input_tokens_spent": spent["tokens"],
            "budget_capped": spent["tokens"] >= max_input_tokens,
            "ran_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        },
        "arms": summarize_live(per_arm),
    }
    out_dir = Path(results_root)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = out_dir / f"summary-{stamp}.json"
    if out.exists():
        raise RuntimeError(f"result collision: {out} exists")
    out_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    summary["path"] = str(out)
    return summary


def _aggregate(rows: list[dict]) -> dict:
    n = max(1, len(rows))
    hits = sum(r.get("cache_hits", 0) for r in rows)
    misses = sum(r.get("cache_misses", 0) for r in rows)
    return {
        "n_tasks": len(rows),
        "success_rate": round(sum(1 for r in rows if r["success"]) / n, 4),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r.get("output_tokens", 0) for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "cache_hit_rate": round(hits / max(1, hits + misses), 4),
        "probes_failed": sum(r.get("probes_failed", 0) for r in rows),
        "calls": sum(r.get("calls", 0) for r in rows),
    }


def _require_key(provider: str) -> str:
    import os

    env = API_KEY_ENV.get(provider)
    if env is None:
        raise SystemExit(f"unknown provider {provider!r}; choose one of {sorted(API_KEY_ENV)}")
    key = os.environ.get(env)
    if not key:
        raise SystemExit(f"{env} is not set; export the provider key first")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Live real-model arm comparison")
    parser.add_argument("--provider", required=True, choices=sorted(API_KEY_ENV))
    parser.add_argument("--model", default=None, help="override the catalog-picked model id")
    parser.add_argument("--arms", default=",".join(DEFAULT_LIVE_ARMS))
    parser.add_argument("--families", default=",".join(FAMILIES))
    parser.add_argument("--seeds", default="0,1")
    parser.add_argument("--pause-s", type=float, default=2.0)
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=DEFAULT_TOKEN_BUDGET,
        help="stop the run (gracefully) after this many cumulative input tokens",
    )
    args = parser.parse_args()

    summary = live_compare(
        provider=args.provider,
        arms=tuple(s.strip() for s in args.arms.split(",") if s.strip()),
        families=tuple(s.strip() for s in args.families.split(",") if s.strip()),
        seeds=tuple(int(s) for s in args.seeds.split(",") if s.strip()),
        model=args.model,
        pause_s=args.pause_s,
        max_input_tokens=args.max_input_tokens,
    )
    print("| arm | " + " | ".join(next(iter(summary["arms"].values())).keys()) + " |")
    for arm, fams in summary["arms"].items():
        cells = " | ".join(
            f"{f['input_tokens']:,} tok ({f['savings_frac']:.0%}), acc {f['success_rate']:.2f}"
            for f in fams.values()
        )
        print(f"| {arm} | {cells} |")
    print(f"manifest: {summary['path']}")


if __name__ == "__main__":
    main()
