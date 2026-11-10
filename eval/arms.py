"""Offline arm implementations (spec Section 9, "Arms").

Six of the eight registered arms run offline against the deterministic task
suite. The other two are excluded here by construction, not by omission:
`provider_native_anthropic` is model-specific and needs a real Anthropic key
(reported separately per spec), and `aperture_learned` is the P3 bandit.

Baseline strategies are re-implemented model-agnostically inside the
selector protocol - they see the same `Features` observation the tuned
selector sees. Their numbers are therefore *this harness's measurements* of
those strategies, not vendor numbers (spec: everything is re-measured;
vendor-reported figures are never copied into results).
"""

from __future__ import annotations

from aperture import Aperture
from aperture.interfaces import PlannedOp, Reward
from aperture.policy.fallback import HeuristicSelector
from aperture.session import Features

# The tuned fixed-heuristic point (eval/tune.py, results/tuning/).
TUNED_BALANCED = {"threshold": 0.5, "keep_n": 6, "dedupe_at": 0.2}

ARMS_OFFLINE: tuple[str, ...] = (
    "full_history",
    "keep_recent_tuned",
    "threshold_edit_compact",
    "acon_always_compress",
    "headroom_proxy",
    "aperture_fixed",
)


class AlwaysCompress:
    """Arm 5 (ACON-style, re-measured): compress the oldest droppable spans
    into one summary every single step, regardless of budget pressure."""

    def select(self, f: Features) -> list[PlannedOp]:
        return [PlannedOp(op="summarize", params={"max_spans": 8}, order=0)]

    def update(self, r: Reward) -> None:
        pass

    def fallback(self) -> list[PlannedOp]:
        return [PlannedOp(op="summarize", params={"max_spans": 8}, order=0)]


class ToolLoadTrim:
    """Arm 6 (Headroom proxy, re-measured): content-type-aware trimming -
    the newer the bulky tool outputs, the fewer spans a keep needs."""

    def select(self, f: Features) -> list[PlannedOp]:
        load = f.tool_output_tokens_recent
        if load > 800:
            return [PlannedOp(op="keep_recent", params={"keep_n": 4}, order=0)]
        if load > 300:
            return [PlannedOp(op="keep_recent", params={"keep_n": 8}, order=0)]
        return []

    def update(self, r: Reward) -> None:
        pass

    def fallback(self) -> list[PlannedOp]:
        return [PlannedOp(op="keep_recent", params={"keep_n": 4}, order=0)]


def make_aperture(arm: str, model, **kwargs) -> Aperture:
    """Build the Aperture instance for one arm; every arm shares the same
    engine (guardrail), store (archive), and loop - only selection differs."""
    if arm == "full_history":
        return Aperture(model=model, profile="off", **kwargs)
    if arm == "keep_recent_tuned":
        return Aperture(
            model=model,
            selector=HeuristicSelector(
                threshold=TUNED_BALANCED["threshold"], keep_n=TUNED_BALANCED["keep_n"]
            ),
            **kwargs,
        )
    if arm == "threshold_edit_compact":
        return Aperture(model=model, selector=HeuristicSelector(threshold=0.6, keep_n=2), **kwargs)
    if arm == "acon_always_compress":
        return Aperture(model=model, selector=AlwaysCompress(), **kwargs)
    if arm == "headroom_proxy":
        return Aperture(model=model, selector=ToolLoadTrim(), **kwargs)
    if arm == "aperture_fixed":
        return Aperture(model=model, selector=HeuristicSelector(**TUNED_BALANCED), **kwargs)
    raise ValueError(f"unknown offline arm {arm!r}; choose one of {ARMS_OFFLINE}")
