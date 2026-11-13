"""Instrumented replay of the needle_qa live harness: which spans are still in
the window when the final question lands, and does the runtime recover the
needle before the model answers?

Offline-only (synthetic NeedleModel, no API keys). Mirrors eval.tasks.run_task
exactly, then reports window state at question time + archive search results +
the actual pre-call window. Since P3-1 (evidence-aware proactive
re-admission), the runtime re-admits archived evidence BEFORE the call when
the question references entities no live span grounds - so the recovery no
longer depends on the synthetic "unknown" convention (which real models
violate; docs/LIVE-FINDINGS.md).
"""

import re
import sys

sys.path.insert(0, "/home/z/my-project/aperture")

from eval.arms import make_aperture  # noqa: E402
from eval.tasks import _QUESTION_RE, FAMILY_BUDGET, build_task, family_model  # noqa: E402

SEED = 0
FAMILY = "needle_qa"


def run(arm: str) -> None:
    plan = build_task(FAMILY, SEED)
    asked = _QUESTION_RE.search(plan.question).group(1)
    sid = f"{FAMILY}-probe-{arm}"

    inner = family_model(FAMILY)
    seen: list = []

    class _Inspect:
        """Capture the pre-call window (what the model actually saw)."""

        def describe(self):
            return inner.describe()

        @property
        def price_list(self):
            return inner.price_list

        def complete(self, window):
            seen.append(window)
            return inner.complete(window)

    ap = make_aperture(arm, _Inspect())
    with ap.chat(sid, token_budget=FAMILY_BUDGET[FAMILY]) as chat:
        chat.system("You are a precise assistant. Reply with the exact value only.")
        chat.raw.register_probe("system-intact", "system", "precise assistant")
        for role, content in plan.turns:
            chat.send(content, role=role)

        # ---- window state at question time ---------------------------------
        hist = chat.history()
        fact_in_window = [c for cls, c in hist if "The answer to the question" in c]
        asked_fact_in_window = [c for c in fact_in_window if asked in c]
        total_turns = len(hist)
        classes = {}
        for cls, _ in hist:
            classes[cls] = classes.get(cls, 0) + 1

        # what the model would see right after the question is appended
        print(f"--- arm={arm} budget={FAMILY_BUDGET[FAMILY]} tok ---")
        print(f"spans in window at question time: {total_turns}  by class: {classes}")
        print(
            f"fact spans still in window: {len(fact_in_window)}/4; "
            f"asked fact present: {bool(asked_fact_in_window)}"
        )
        for i, (cls, c) in enumerate(hist):
            print(f"  [{i:2d}] {cls:12s} {c[:64]!r}")

        # ---- archive recovery capability -----------------------------------
        hits = ap.store.archive_search(sid, plan.question, top_k=3, span_class="conversation")
        print(f"archive_search(top_k=3, conversation) hits: {len(hits)}")
        for h in hits:
            mark = "  <-- ASKED FACT RECOVERABLE" if asked in h.content else ""
            print(f"  archive: {h.content[:64]!r}{mark}")
        needle_recoverable = any(asked in h.content for h in hits)

        # ---- what actually happens next ------------------------------------
        # P3-1: the runtime re-admits archived evidence BEFORE the call when
        # the question references entities no live span grounds; the synthetic
        # "unknown" retry below is now only a fallback.
        reply = chat.send(plan.question)
        pre_call = seen[-1] if seen else None  # the question-time pre-call window
        retried = False
        if reply.strip().lower() == "unknown":
            retried = True
            hits2 = ap.store.archive_search(sid, plan.question, top_k=3, span_class="conversation")
            for h in hits2:
                chat.ingest(h.content, role="tool")
            reply = chat.send(plan.question)
        graded = re.search(rf"\b{re.escape(plan.expected)}\b", reply) is not None
        if pre_call is not None:
            pre_call_facts = [
                s for s in pre_call.spans if "The answer to the question" in s.content
            ]
            pre_call_asked = [s for s in pre_call_facts if asked in s.content]
            retrieved = [s for s in pre_call.spans if s.span_class == "retrieved"]
            print(
                f"pre-call window: {len(pre_call.spans)} spans; "
                f"asked fact present: {bool(pre_call_asked)}; "
                f"re-admitted spans: {len(retrieved)}"
            )
        print(
            f"needle recoverable from archive: {needle_recoverable}; "
            f"synthetic 'unknown' retry fired: {retried}; final reply: {reply!r}; graded: {graded}"
        )
        print()


if __name__ == "__main__":
    for arm in ("keep_recent_tuned", "aperture_fixed", "full_history"):
        run(arm)
