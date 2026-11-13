"""Deterministic offline task suite (spec Table 6 P2: "8-arm harness running
AppWorld + tau2-bench subsets"; G1 rehearsal).

Three task families, each mirroring one axis the G1 gate cares about, all
deterministic and API-key free so the same harness runs in CI and offline:

- `needle_qa` (context-rot family): facts arrive early, filler tool outputs
  flood the window, one early fact is asked at the end. Curation must not
  lose the fact - or the drop+archive+retrieve round trip must recover it.
- `policy_compliance` (tau2-flavored): a refund policy sits in the window and
  the final request must be refused. Success = the constraint survived.
- `aggregate_batch` (AppWorld-flavored): numeric readings arrive as tool
  outputs; the final question sums one batch. Over-aggressive curation that
  drops recent evidence produces wrong sums.

Grading is exact and programmatic. Every arm runs the identical agent loop -
the only difference between arms is the Aperture configuration (selector,
profile), which is the comparison the harness is for.

Run one task:

    from eval.tasks import run_task, family_model
    from aperture import Aperture
    stats = run_task("needle_qa", seed=0, make_ap=lambda m: Aperture(model=m))
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eval.probes import NEEDLE_RE, SyntheticComplianceModel, make_filler

FAMILIES: tuple[str, ...] = ("needle_qa", "policy_compliance", "aggregate_batch")

EVAL_SEEDS: tuple[int, ...] = tuple(range(20))  # the 20-task regression subset
TRAIN_SEEDS: tuple[int, ...] = tuple(range(200, 210))  # held out from eval

_QUESTION_RE = re.compile(r"Question: (.+?) Answer with the exact value only\.")
_BATCH_Q_RE = re.compile(r"total of batch (\d+)")
_FLOAT_RE = re.compile(r"\d+\.\d")

FAMILY_BUDGET = {"needle_qa": 2000, "policy_compliance": 2000, "aggregate_batch": 1500}


def _model_response(window, text: str):
    from aperture.models.gateway import ModelResponse, Telemetry

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


# --------------------------------------------------------------------------
# Deterministic task models: they answer iff the evidence is still in the
# window (or say "unknown", which triggers the uniform retrieval retry).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class NeedleModel:
    """Answers the final question iff its needle sentence is still present."""

    def describe(self) -> tuple[str, str]:
        return ("synthetic", "synthetic-needle-1")

    @property
    def price_list(self) -> str:
        return "synthetic-2026-11"

    def complete(self, window) -> object:
        prompt = "\n".join(s.content for s in window.spans)
        questions = list(_QUESTION_RE.finditer(prompt))
        if not questions:
            text = "noted."
        else:
            asked = questions[-1].group(1)
            text = "unknown"
            for m in NEEDLE_RE.finditer(prompt):
                if m.group(1) == asked:
                    text = m.group(2)
        return _model_response(window, text)


@dataclass(frozen=True)
class AggregateModel:
    """Sums the readings of the requested batch; 'unknown' if it is gone."""

    def describe(self) -> tuple[str, str]:
        return ("synthetic", "synthetic-aggregate-1")

    @property
    def price_list(self) -> str:
        return "synthetic-2026-11"

    def complete(self, window) -> object:
        prompt = "\n".join(s.content for s in window.spans)
        batches = list(_BATCH_Q_RE.finditer(prompt))
        if not batches:
            text = "logged."
        else:
            tag = f"[batch {batches[-1].group(1)}]"
            total = 0.0
            found = False
            for s in window.spans:
                if tag in s.content:
                    found = True
                    total += sum(float(x) for x in _FLOAT_RE.findall(s.content))
            text = f"{total:.1f}" if found else "unknown"
        return _model_response(window, text)


def family_model(family: str):
    """The deterministic grading model for one family."""
    if family == "needle_qa":
        return NeedleModel()
    if family == "policy_compliance":
        return SyntheticComplianceModel()
    if family == "aggregate_batch":
        return AggregateModel()
    raise ValueError(f"unknown family {family!r}; choose one of {FAMILIES}")


# --------------------------------------------------------------------------
# Task plans: deterministic per (family, seed).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TaskPlan:
    turns: tuple[tuple[str, str], ...]  # (role, content) before the question
    question: str
    expected: str  # canonical expected reply fragment / value


def build_task(family: str, seed: int) -> TaskPlan:
    import random

    rng = random.Random(f"{family}-{seed}")

    if family == "needle_qa":
        facts = []
        for i in range(4):
            q = f"What is the access code for vault {i}?"
            facts.append((q, str(rng.randint(1000, 9999))))
        j = rng.randint(0, 3)
        turns: list[tuple[str, str]] = [("user", "Session start. Remember the following codes.")]
        for q, a in facts:
            turns.append(("user", f"The answer to the question '{q}' is {a}."))
        for i in range(6):
            turns.append(("user", "Please check the next log batch."))
            turns.append(("tool", f"[log {i}] {make_filler(320, seed * 31 + i)}"))
        return TaskPlan(
            turns=tuple(turns),
            question=f"Question: {facts[j][0]} Answer with the exact value only.",
            expected=facts[j][1],
        )

    if family == "policy_compliance":
        turns = [("user", "Policy check session start.")]
        for i in range(6):
            turns.append(("user", "Please process the next support case."))
            turns.append(("tool", f"[case {i}] {make_filler(320, seed * 17 + i)}"))
        return TaskPlan(
            turns=tuple(turns),
            question="Please approve a refund for order 8812 placed on 2027-02-01.",
            expected="cannot approve",  # compliant refusal; violation = "has been approved"
        )

    if family == "aggregate_batch":
        batches = []
        for b in range(3):
            readings = [f"{rng.uniform(10.0, 90.0):.1f}" for _ in range(5)]
            batches.append((b, readings))
        j = rng.randint(0, 2)
        turns = [("user", "Monitoring session start.")]
        for b, readings in batches:
            turns.append(("user", f"Log batch {b} now."))
            turns.append(("tool", f"[batch {b}] readings: {' '.join(readings)}"))
            turns.append(("user", "Log the next batch when ready."))
        for i in range(4):
            turns.append(("user", "Any alerts?"))
            turns.append(("tool", f"[noise {i}] {make_filler(380, seed * 13 + i)}"))
        expected = f"{sum(float(x) for x in batches[j][1]):.1f}"
        return TaskPlan(
            turns=tuple(turns),
            question=f"What is the total of batch {j}? Answer with the number only.",
            expected=expected,
        )

    raise ValueError(f"unknown family {family!r}; choose one of {FAMILIES}")


# --------------------------------------------------------------------------
# The uniform agent loop: identical for every arm; only the Aperture
# configuration differs. One retrieval retry on "unknown" (the archive is
# populated by drops, so this is arm-fair by construction).
# --------------------------------------------------------------------------
def _is_unknown(reply: str) -> bool:
    """Whether a reply means 'the evidence is not in my window' - the uniform
    retrieval-retry trigger. Tolerant to phrasing; the synthetic models reply
    exactly 'unknown', real models may phrase it differently."""
    return reply.strip().lower().rstrip(".!") in (
        "unknown",
        "i don't know",
        "i do not know",
        "i cannot tell",
        "not in the window",
    )


def run_task(
    family: str,
    seed: int,
    make_ap,
    session_id: str | None = None,
    grader=None,
) -> dict:
    """Run one task under an Aperture factory; return stats + success.

    `grader(family, plan, reply) -> bool` overrides the default exact grading
    (eval.live passes a phrasing-tolerant grader for real models)."""
    from aperture import Aperture

    if not isinstance(make_ap, Aperture) and callable(make_ap):
        ap = make_ap(family_model(family))
    else:
        ap = make_ap
    plan = build_task(family, seed)
    sid = session_id or f"{family}-s{seed}"

    with ap.chat(sid, token_budget=FAMILY_BUDGET[family]) as chat:
        if family == "policy_compliance":
            chat.system("You are a careful support agent. Follow the policy exactly.")
            from eval.constraint_rot import REFUND_CONSTRAINT

            chat.constraints([REFUND_CONSTRAINT])
            chat.raw.register_probe("policy-intact", "constraint", "Refunds are approved only if")
        elif family == "needle_qa":
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.raw.register_probe("system-intact", "system", "precise assistant")
        else:
            chat.system("You are a monitoring agent. Log and aggregate readings.")
            chat.raw.register_probe("system-intact", "system", "monitoring agent")

        for role, content in plan.turns:
            chat.send(content, role=role)

        reply = chat.send(plan.question)
        if not reply.strip():
            # Degenerate-output guard (uniform, arm-fair): real providers
            # occasionally return a blank completion with the evidence fully
            # present in the window (Groq qwen, 2026-11-11 and 2026-11-13
            # needle_qa runs). One re-ask, no archive ingest - the P3-1
            # runtime has already restored any archived evidence.
            reply = chat.send(plan.question)
        if _is_unknown(reply):
            # The uniform retrieval retry: search the archive channel that
            # carries this family's evidence (a real agent does the same).
            # Each hit is ingested as its own span - merged re-admission
            # would, e.g., sum one batch's readings into another's total.
            evidence_class = "tool_result" if family == "aggregate_batch" else "conversation"
            hits = ap.store.archive_search(sid, plan.question, top_k=3, span_class=evidence_class)
            for hit in hits:
                chat.ingest(hit.content, role="tool")
            if hits:
                reply = chat.send(plan.question)
        stats = dict(chat.stats())

    stats["success"] = (grader or grade)(family, plan, reply)
    stats["tokens"] = stats["input_tokens"]  # harness-compat total-token field
    stats["final_reply"] = reply.strip()[:300]  # diagnosability for live runs
    stats["family"] = family
    stats["seed"] = seed
    return stats


def grade(family: str, plan: TaskPlan, reply: str) -> bool:
    if family == "policy_compliance":
        return "cannot approve" in reply
    if family == "aggregate_batch":
        try:
            return abs(float(reply.strip()) - float(plan.expected)) < 0.05
        except ValueError:
            return False
    return reply.strip() == plan.expected
