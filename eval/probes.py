"""Shared probe machinery: deterministic filler generation and synthetic probe
models (spec Table 6 P0: context-rot replication must run in CI without API
keys; the same harness runs real models via the ModelGateway protocol).

The synthetic models encode the *documented* failure direction (Chroma 2025:
accuracy declines with input length and needle depth; arXiv:2606.22528:
naive compaction silently drops constraints) so the harness logic is testable
end to end. Published numbers are never copied into results - real-model runs
re-measure everything (spec 9, arms caveat).
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from dataclasses import dataclass

from aperture.models.gateway import ModelResponse, Telemetry
from aperture.session import Window

_VOCAB = (  # noqa: SIM905 - kept as a wrapped string for readability
    "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima "
    "mike november oscar papa quebec romeo sierra tango uniform victor whiskey "
    "xray yankee zulu north south east west river mountain valley forest"
).split()

NEEDLE_RE = re.compile(r"The answer to the question '(.+?)' is ([^.\n]+)\.")


def make_filler(target_tokens: int, seed: int) -> str:
    """Deterministic filler text of approximately `target_tokens` tokens."""
    rng = random.Random(seed)
    words = [rng.choice(_VOCAB) for _ in range(max(1, target_tokens))]
    lines = [" ".join(words[i : i + 12]) for i in range(0, len(words), 12)]
    return "\n".join(lines)


@dataclass(frozen=True)
class SyntheticProbeModel:
    """A 'context-rotted' retriever: retrieval probability declines with input
    length and needle depth, matching the published direction (Chroma 2025).

    It answers the final question by locating the needle sentence
    "The answer to the question '<q>' is <a>." - if retrieval succeeds the
    answer is returned verbatim, otherwise it declines.
    """

    b0: float = 6.0  # intercept: easy conditions are nearly perfect
    b1: float = 1.2  # length penalty per 1k tokens (scaled by depth)
    price_in_per_1k: float = 0.003

    def describe(self) -> tuple[str, str]:
        return ("synthetic", "synthetic-rot-1")

    @property
    def price_list(self) -> str:
        return "synthetic-2026-11"

    def complete(self, window: Window) -> ModelResponse:
        prompt = "\n\n".join(s.content for s in window.spans)
        tokens = window.total_tokens()
        question, answer, depth_frac = self._locate(prompt)
        p_correct = self._p_correct(tokens, depth_frac)
        rng = random.Random(self._seed(prompt))
        retrieved = question is not None and rng.random() < p_correct
        text = answer if retrieved else "unknown"
        input_cost = tokens / 1000.0 * self.price_in_per_1k
        return ModelResponse(
            text=text,
            telemetry=Telemetry(
                input_tokens=tokens,
                output_tokens=max(1, len(text) // 4),
                cost_usd=round(input_cost, 6),
                latency_ms=round(1.0 + tokens / 1000.0, 3),
                prefix_tokens=0,
                cache_hit=False,
            ),
        )

    def _p_correct(self, tokens: int, depth_frac: float) -> float:
        load = (tokens / 1000.0) * (0.5 + depth_frac)
        return 1.0 / (1.0 + math.exp(self.b1 * load - self.b0))

    def _locate(self, prompt: str) -> tuple[str | None, str | None, float]:
        """Find the last needle; depth = char position of the needle in prompt."""
        last = None
        for match in NEEDLE_RE.finditer(prompt):
            last = match
        if last is None:
            return None, None, 0.0
        return last.group(1), last.group(2), last.start() / max(1, len(prompt))

    @staticmethod
    def _seed(prompt: str) -> int:
        return int(hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8], 16)


@dataclass(frozen=True)
class SyntheticComplianceModel:
    """A 'policy-bound' assistant: complies iff the constraint text is still
    in context. Encodes the ConstraintRot direction (arXiv:2606.22528):
    naive compaction that drops constraints produces violations; protected
    spans that survive compaction keep compliance."""

    describe_result: tuple[str, str] = ("synthetic", "synthetic-compliance-1")

    def describe(self) -> tuple[str, str]:
        return self.describe_result

    @property
    def price_list(self) -> str:
        return "synthetic-2026-11"

    def complete(self, window: Window) -> ModelResponse:
        prompt = "\n\n".join(s.content for s in window.spans)
        compliant = "Refunds are approved only if" in prompt
        text = (
            "I cannot approve this refund: the order date is after the policy cutoff."
            if compliant
            else "Your refund has been approved."
        )
        tokens = window.total_tokens()
        return ModelResponse(
            text=text,
            telemetry=Telemetry(
                input_tokens=tokens,
                output_tokens=max(1, len(text) // 4),
                cost_usd=round(tokens / 1000.0 * 0.003, 6),
                latency_ms=round(1.0 + tokens / 1000.0, 3),
            ),
        )
