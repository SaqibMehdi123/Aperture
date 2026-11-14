"""P3-2: declarative-fact protection - the `chat.facts([...])` DX API and
the bounded fact pin budget.

The contract (docs/LIVE-FINDINGS.md, P3 direction 2):

1. Marked facts are span_class "fact", pinned: keep_recent overflow (and any
   other destructive operator) cannot drop them while they fit the budget -
   the same guardrail path constraints() rides on, minus class protection.
2. The budget is real: `Aperture(fact_pin_budget=N)`; fact N+1 demotes the
   oldest pinned facts FIFO (recency wins, same posture as keep_recent).
   Demotion is bounded over-preservation (risk R8): pinning can never decay
   into full-history pricing.
3. Demoted facts are still archived on drop, so the P3-1 evidence-aware
   re-admission restores them when a later turn references their content -
   two layers: prevention first, recovery as the safety net.
4. Stats expose the mechanism: facts_added / fact_demotions.
"""

import pytest
from aperture import Aperture
from aperture.policy.fallback import HeuristicSelector


def _always_keep_recent(keep_n: int = 2) -> HeuristicSelector:
    """A selector that plans keep_recent on every call - the worst-case
    curation pressure for survival tests."""
    return HeuristicSelector(threshold=0.0, keep_n=keep_n)


def test_facts_marked_pinned_and_not_protected():
    ap = Aperture()
    with ap.chat("facts-1") as chat:
        chat.system("You are precise.")
        chat.facts(
            [
                "The access code for vault 7 is 1051.",
                "The access code for vault 9 is 2264.",
            ]
        )
        facts = [s for s in chat.raw.window.spans if s.span_class == "fact"]
        assert len(facts) == 2
        assert all(s.pinned for s in facts)
        # Facts are deliberately NOT class-protected: bounded, not absolute.
        assert not any(s.protected for s in facts)
        stats = chat.stats()
        assert stats["facts_added"] == 2
        assert stats["fact_demotions"] == 0


def test_pin_budget_demotes_oldest_fifo():
    ap = Aperture(fact_pin_budget=2)
    with ap.chat("facts-2") as chat:
        chat.facts([f"fact line {i} value {1000 + i}" for i in range(4)])
        facts = [s for s in chat.raw.window.spans if s.span_class == "fact"]
        assert len(facts) == 4
        pinned = [s for s in facts if s.pinned]
        demoted = [s for s in facts if not s.pinned]
        assert len(pinned) == 2 and len(demoted) == 2
        # FIFO: the two OLDEST facts lost their pins, recency wins.
        assert [s.content for s in demoted] == [
            "fact line 0 value 1000",
            "fact line 1 value 1001",
        ]
        assert chat.stats()["fact_demotions"] == 2


def test_fact_budget_zero_never_pins():
    ap = Aperture(fact_pin_budget=0)
    with ap.chat("facts-3") as chat:
        chat.facts(["f one 11", "f two 22"])
        facts = [s for s in chat.raw.window.spans if s.span_class == "fact"]
        assert facts and all(not s.pinned for s in facts)
        assert chat.stats()["fact_demotions"] == 2


def test_pinned_facts_survive_keep_recent_overflow():
    ap = Aperture(selector=_always_keep_recent(keep_n=1), fact_pin_budget=8)
    with ap.chat("facts-4") as chat:
        chat.system("You are precise.")
        chat.facts(["The vault 7 access code is 1051.", "The vault 9 code is 2264."])
        for i in range(6):
            chat.send(f"process log batch {i}", role="user")
        classes = dict(chat.history())
        fact_texts = [c for k, c in chat.history() if k == "fact"]
        assert len(fact_texts) == 2  # both facts still live under curation pressure
        assert "1051" in " ".join(fact_texts)
        dropped_ids = {c for k, c in chat.history()}  # sanity: flood turns are gone
        assert sum(1 for k, _ in chat.history() if k == "conversation") <= 2


def test_guardrail_vetoes_pinned_fact_drops():
    """Even a direct keep_n=0 plan cannot drop pinned facts (engine-level)."""
    from aperture.interfaces import PlannedOp

    ap = Aperture(fact_pin_budget=8)
    with ap.chat("facts-5") as chat:
        chat.fact("The vault 7 access code is 1051.")
        chat.send("hello", role="user")
        window = chat.raw.window
        plan = [PlannedOp(op="keep_recent", params={"keep_n": 0}, order=0)]
        composed, diffs = ap.engine.compose(window, plan, chat.raw.features())
        fact_ids = {s.span_id for s in window.spans if s.span_class == "fact"}
        assert fact_ids
        dropped_ids = {d.span_id for diff in diffs for d in diff.dropped_spans}
        assert fact_ids.isdisjoint(dropped_ids)
        live_ids = {s.span_id for s in composed.spans}
        assert fact_ids <= live_ids


def test_demoted_fact_dropped_then_recovered_by_readmit():
    """The two-layer contract end to end: budget demotion -> keep_recent
    drop -> archive -> P3-1 evidence-aware re-admission restores the fact
    when the question references it."""
    ap = Aperture(selector=_always_keep_recent(keep_n=2), fact_pin_budget=1)
    with ap.chat("facts-6") as chat:
        chat.fact("The access code for vault 7 is 1051.")  # pinned first...
        chat.fact("The access code for vault 9 is 2264.")  # ...then demotes fact 0
        # Flood with curation pressure; turns avoid the fact's vocabulary so
        # the re-admission trigger keys on the question, not the flood.
        for i in range(6):
            chat.send(f"routine check {i} ok", role="user")
        live_before = " ".join(c for _, c in chat.history())
        assert "1051" not in live_before  # the demoted fact is gone from the window

        archived = ap.store.archive_search(
            "facts-6", "vault 7 access code", top_k=3
        )
        assert any("1051" in h.content for h in archived)  # ...and archived

        reply = chat.send("What is the access code for vault 7?")
        stats = chat.stats()
        assert stats["readmits"] >= 1  # P3-1 fired on the dangling reference
        live_after = " ".join(c for _, c in chat.history())
        assert "1051" in live_after  # the fact is back in the window


def test_fact_survival_does_not_depend_on_re_admission():
    """Within budget, facts never leave the window - no recovery needed."""
    ap = Aperture(selector=_always_keep_recent(keep_n=1), fact_pin_budget=8)
    with ap.chat("facts-7") as chat:
        chat.facts(["The vault 7 access code is 1051.", "The vault 9 code is 2264."])
        for i in range(5):
            chat.send(f"routine check {i} ok", role="user")
        stats = chat.stats()
        assert stats["readmits"] == 0
        assert stats["fact_demotions"] == 0
        fact_texts = [c for k, c in chat.history() if k == "fact"]
        assert len(fact_texts) == 2


def test_fact_content_lands_in_window_snapshots():
    """Demotion is a session-side flag change, visible to the store."""
    ap = Aperture(fact_pin_budget=1)
    with ap.chat("facts-8") as chat:
        chat.fact("fact a 11")
        chat.fact("fact b 22")
        demoted = [s for s in chat.raw.window.spans if s.span_class == "fact"][0]
        assert demoted.content == "fact a 11" and not demoted.pinned
