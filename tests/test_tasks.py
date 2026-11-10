"""P2 task suite: determinism, grading, and the drop+retrieve story."""

from pathlib import Path

from aperture import Aperture
from aperture.policy.fallback import HeuristicSelector
from aperture.trace.ledger import TraceLedger
from eval.tasks import (
    EVAL_SEEDS,
    FAMILIES,
    build_task,
    run_task,
)


def _ap_factory(**kwargs):
    def factory(model):
        return Aperture(model=model, **kwargs)

    return factory


def test_build_task_is_deterministic_per_seed():
    for family in FAMILIES:
        a = build_task(family, seed=3)
        b = build_task(family, seed=3)
        assert a == b
        c = build_task(family, seed=4)
        assert a != c  # seeds produce genuinely different tasks


def test_every_family_runs_and_grades_full_history(tmp_path):
    """profile='off' keeps everything -> every task must succeed."""
    for family in FAMILIES:
        stats = run_task(family, seed=0, make_ap=_ap_factory(profile="off"))
        assert stats["success"], f"full history must succeed on {family}"
        assert stats["calls"] > 0
        assert stats["input_tokens"] > 0


def test_balanced_arm_succeeds_via_curation_plus_retrieval(tmp_path):
    """The flagship story: curation drops, archive remembers, retrieval recovers."""
    for family in FAMILIES:
        stats = run_task(family, seed=1, make_ap=_ap_factory(profile="balanced"))
        assert stats["success"], f"balanced arm must succeed on {family}"
        assert stats["input_tokens"] > 0


def test_run_is_deterministic_same_config_same_tokens():
    a = run_task("needle_qa", seed=2, make_ap=_ap_factory(profile="balanced"))
    b = run_task("needle_qa", seed=2, make_ap=_ap_factory(profile="balanced"))
    assert a["input_tokens"] == b["input_tokens"]
    assert a["calls"] == b["calls"]
    assert a["success"] == b["success"]


def test_every_step_is_traced(tmp_path):
    """G1 criterion: 100% of curation decisions logged with diffs."""
    ledger_path = Path(tmp_path) / "trace.jsonl"
    ledger = TraceLedger(ledger_path)
    factory = lambda model: Aperture(  # noqa: E731
        model=model, profile="balanced", ledger=ledger
    )
    stats = run_task("policy_compliance", seed=3, make_ap=factory)
    records = list(ledger.records())
    assert len(records) == stats["calls"]
    assert all(r.diffs is not None for r in records)


def test_eval_seeds_are_the_regression_subset():
    assert len(EVAL_SEEDS) == 20
    assert not set(EVAL_SEEDS) & set(range(200, 210))
    assert all(build_task(f, s).question for f in FAMILIES for s in EVAL_SEEDS[:3])


def test_aggressive_curation_still_recovers(tmp_path):
    """Even keep_n=1 succeeds: unknown -> archive -> retrieval -> re-answer."""
    factory = _ap_factory(
        selector=HeuristicSelector(threshold=0.1, keep_n=1),
    )
    stats = run_task("needle_qa", seed=4, make_ap=factory)
    assert stats["success"]
    assert stats["calls"] > run_task_calls_baseline  # retrieval retry cost


run_task_calls_baseline = run_task("needle_qa", seed=4, make_ap=_ap_factory(profile="off"))["calls"]
