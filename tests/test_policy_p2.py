"""P2 selector tuning: the dedupe knob on the fixed heuristic."""

from aperture.policy.fallback import HeuristicSelector
from aperture.session import Features


def _features(budget: float = 0.9, redundancy: float = 0.5) -> Features:
    return Features(
        budget_used_frac=budget,
        task_phase="act",
        tool_output_tokens_recent=0,
        redundancy_score=redundancy,
        drift_score=0.0,
        prefix_hash="p",
    )


def test_dedupe_planned_when_redundancy_reaches_knob():
    plan = HeuristicSelector(threshold=1.01, dedupe_at=0.3).select(_features(redundancy=0.4))
    assert [p.op for p in plan] == ["dedupe"]


def test_dedupe_disabled_by_default():
    plan = HeuristicSelector().select(_features())
    assert all(p.op != "dedupe" for p in plan)


def test_keep_recent_at_threshold_and_ordering():
    plan = HeuristicSelector(threshold=0.7, keep_n=6, dedupe_at=0.2).select(
        _features(budget=0.8, redundancy=0.5)
    )
    assert [p.op for p in plan] == ["dedupe", "keep_recent"]
    assert plan[1].params == {"keep_n": 6}


def test_noop_below_threshold():
    assert HeuristicSelector(threshold=0.7).select(_features(budget=0.5, redundancy=0.0)) == []


def test_balanced_profile_is_the_tuned_point():
    """The shipped default must stay the tuned point (results/tuning/)."""
    from aperture.runtime import PROFILES

    assert PROFILES["balanced"] == {"threshold": 0.5, "keep_n": 6, "dedupe_at": 0.2}
    sel = HeuristicSelector(**PROFILES["balanced"])
    assert (sel.threshold, sel.keep_n, sel.dedupe_at) == (0.5, 6, 0.2)
