"""Instrumented replay of the needle_qa live harness: which spans are still in
the window when the final question lands, and could the archive recover the
needle if the real model said "unknown" instead of guessing?

Offline-only (synthetic NeedleModel, no API keys). Mirrors eval.tasks.run_task
exactly, then reports window state at question time + archive search results.
"""

import re
import sys

sys.path.insert(0, "/home/z/my-project/aperture")

from eval.arms import make_aperture  # noqa: E402
from eval.probes import NEEDLE_RE  # noqa: E402
from eval.tasks import FAMILY_BUDGET, _QUESTION_RE, build_task, family_model  # noqa: E402

SEED = 0
FAMILY = "needle_qa"


def run(arm: str) -> None:
    plan = build_task(FAMILY, SEED)
    asked = _QUESTION_RE.search(plan.question).group(1)
    needle_sentence = f"The answer to the question '{asked}' is {plan.expected}."
    sid = f"{FAMILY}-probe-{arm}"

    ap = make_aperture(arm, family_model(FAMILY))
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
        print(f"fact spans still in window: {len(fact_in_window)}/4; asked fact present: {bool(asked_fact_in_window)}")
        for i, (cls, c) in enumerate(hist):
            print(f"  [{i:2d}] {cls:12s} {c[:64]!r}")

        # ---- archive recovery capability -----------------------------------
        hits = ap.store.archive_search(sid, plan.question, top_k=3, span_class="conversation")
        print(f"archive_search(top_k=3, conversation) hits: {len(hits)}")
        for h in hits:
            mark = "  <-- ASKED FACT RECOVERABLE" if asked in h.content else ""
            print(f"  archive: {h.content[:64]!r}{mark}")
        needle_recoverable = any(asked in h.content for h in hits)

        # ---- what actually happens next (synthetic model = 'unknown' path) --
        reply = chat.send(plan.question)
        retried = False
        if reply.strip().lower() == "unknown":
            retried = True
            hits2 = ap.store.archive_search(sid, plan.question, top_k=3, span_class="conversation")
            for h in hits2:
                chat.ingest(h.content, role="tool")
            reply = chat.send(plan.question)
        graded = re.search(rf"\b{re.escape(plan.expected)}\b", reply) is not None
        print(f"needle recoverable from archive: {needle_recoverable}; "
              f"synthetic 'unknown' retry fired: {retried}; final reply: {reply!r}; graded: {graded}")
        print()


if __name__ == "__main__":
    for arm in ("keep_recent_tuned", "aperture_fixed", "full_history"):
        run(arm)
