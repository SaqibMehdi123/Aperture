"""Context-rot replication probes (spec Table 6 P0; Table 9 rows LongMemEval
and Extended NIAH).

Two suites, both runnable against any ModelGateway:

- `niah_probe`: extended needle-in-a-haystack over a depth x length grid
  (Chroma protocol: accuracy is a joint function of both, not length alone).
- `focused_vs_full_probe`: LongMemEval-style focused-vs-full - the same
  question answered over the focused subset vs the full history isolates the
  rot a curation runtime must prevent, and yields the token delta.

Outputs are RotCurves / summary dicts written as JSON; the replication memo
(weeks 3-4) charts them against the published direction.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from eval.probes import SyntheticProbeModel, make_filler

QUESTION = "What is the magic number?"


@dataclass(frozen=True)
class RotPoint:
    depth_frac: float
    filler_tokens: int
    trials: int
    accuracy: float


@dataclass
class RotCurve:
    suite: str
    model_id: str
    points: list[RotPoint] = field(default_factory=list)


def niah_prompt(depth_frac: float, filler_tokens: int, seed: int, magic: str) -> str:
    """Needle buried at `depth_frac` of the filler; question at the end."""
    pre = make_filler(int(filler_tokens * depth_frac), seed)
    post = make_filler(filler_tokens - int(filler_tokens * depth_frac), seed + 1)
    needle = f"The answer to the question '{QUESTION}' is {magic}."
    return f"{pre}\n{needle}\n{post}\n\nQuestion: {QUESTION}\nAnswer with the exact value only."


def niah_probe(
    model=None,
    lengths: tuple[int, ...] = (1000, 2000, 4000, 8000),
    depths: tuple[float, ...] = (0.1, 0.3, 0.5, 0.7, 0.9),
    trials: int = 3,
    seed: int = 0,
) -> RotCurve:
    model = model if model is not None else SyntheticProbeModel()
    _, model_id = model.describe()
    curve = RotCurve(suite="extended_niah", model_id=model_id)
    from aperture.session import Span, Window

    for length in lengths:
        for depth in depths:
            hits = 0
            for t in range(trials):
                magic = str(1000 + seed * 977 + length + t)
                prompt = niah_prompt(depth, length, seed + 1000 * t, magic)
                window = Window(
                    token_budget=10**9,
                    spans=[
                        Span(
                            span_id=f"n{length}-{depth}-{t}",
                            span_class="probe",
                            content=prompt,
                        )
                    ],
                )
                answer = model.complete(window).text.strip()
                hits += int(answer == magic)
            curve.points.append(
                RotPoint(
                    depth_frac=depth,
                    filler_tokens=length,
                    trials=trials,
                    accuracy=round(hits / trials, 4),
                )
            )
    return curve


def focused_vs_full_probe(
    model=None,
    filler_tokens: int = 4000,
    n_facts: int = 6,
    seed: int = 7,
) -> dict:
    """Same question, focused subset vs full history (LongMemEval protocol)."""
    model = model if model is not None else SyntheticProbeModel()
    _, model_id = model.describe()
    from aperture.session import Span, Window

    facts = [(f"What is the capital of country-{i}?", f"city-{i}") for i in range(n_facts)]
    needle_block = "\n".join(f"The answer to the question '{q}' is {a}." for q, a in facts)
    question, answer = facts[-1]

    full_prompt = (
        f"{needle_block}\n{make_filler(filler_tokens, seed)}\n\n"
        f"Question: {question}\nAnswer with the exact value only."
    )
    focused_prompt = f"{needle_block}\n\nQuestion: {question}\nAnswer with the exact value only."

    full_window = Window(
        token_budget=10**9, spans=[Span(span_id="full", span_class="probe", content=full_prompt)]
    )
    focused_window = Window(
        token_budget=10**9,
        spans=[Span(span_id="focused", span_class="probe", content=focused_prompt)],
    )
    full_correct = model.complete(full_window).text.strip() == answer
    focused_correct = model.complete(focused_window).text.strip() == answer

    tokens_full = full_window.total_tokens()
    tokens_focused = focused_window.total_tokens()
    return {
        "suite": "focused_vs_full",
        "model_id": model_id,
        "acc_full": float(full_correct),
        "acc_focused": float(focused_correct),
        "tokens_full": tokens_full,
        "tokens_focused": tokens_focused,
        "token_savings_frac": round(1.0 - tokens_focused / max(1, tokens_full), 4),
        "filler_tokens": filler_tokens,
        "seed": seed,
    }


def rot_monotone_decline(curve: RotCurve) -> bool:
    """Direction check: accuracy at the hardest condition (max length x depth)
    is strictly below the easiest (min length x depth)."""
    if not curve.points:
        return False

    def load(p: RotPoint) -> float:
        return p.filler_tokens * (0.5 + p.depth_frac)

    easiest = min(curve.points, key=load)
    hardest = max(curve.points, key=load)
    return hardest.accuracy < easiest.accuracy


def save_curve(curve: RotCurve, path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(curve), indent=2), encoding="utf-8")
