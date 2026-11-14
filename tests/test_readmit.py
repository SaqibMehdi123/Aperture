"""Tests for the P3-1 evidence-aware proactive re-admission.

Scenario mirrors docs/LIVE-FINDINGS.md: an early fact is dropped by
curation; the final question still references it. Real models fabricate
instead of saying "unknown", so re-admission must key on evidence coverage
in the window, not on reply text. All tests are offline and deterministic.
"""

from __future__ import annotations

from aperture import Aperture
from aperture.interfaces import PlannedOp
from aperture.policy.fallback import HeuristicSelector
from aperture.readmit import (
    missing_evidence,
    readmit_plan,
    salient_tokens,
    tokenize,
)
from aperture.session import Span, Window

FACT = "Fact 1: The answer to the question 'What is the vault code for room 4?' is 1051."
QUESTION = "Question: What is the vault code for room 4? Answer with the exact value only."


class SpyGateway:
    """Records the window each call sees; replies fixed text."""

    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.windows: list[Window] = []

    def describe(self) -> tuple[str, str]:
        return ("synthetic", "spy-1")

    @property
    def price_list(self) -> str:
        return "spy-2026-11"

    def complete(self, window: Window):
        from aperture.models.gateway import ModelResponse, Telemetry

        self.windows.append(window)
        tokens = window.total_tokens()
        return ModelResponse(
            text=self.reply,
            telemetry=Telemetry(
                input_tokens=tokens,
                output_tokens=1,
                cost_usd=0.0,
                latency_ms=1.0,
            ),
        )


def _window_with(spans: list[tuple[str, str, str]]) -> Window:
    """(span_id, span_class, content) triples -> Window."""
    w = Window(token_budget=4096)
    for span_id, span_class, content in spans:
        w.spans.append(Span(span_id=span_id, span_class=span_class, content=content))
    return w


class TestSalience:
    def test_numbers_are_always_salient(self) -> None:
        # Template words stripped, the batch id survives - the critical
        # dangling-reference class per the live findings.
        assert salient_tokens("What is the total of batch 3?") == {"batch", "3"}

    def test_decimals_tokenize_into_parts(self) -> None:
        assert tokenize("readings 12.5 and 274.5, order 8812") == {
            "readings",
            "12",
            "5",
            "and",
            "274",
            "order",
            "8812",
        }

    def test_template_words_are_stopwords(self) -> None:
        assert salient_tokens(QUESTION) == {"vault", "code", "room", "4"}

    def test_domain_words_stay_salient(self) -> None:
        assert {"vault", "code", "room"} <= salient_tokens("vault code for room 4")


class TestMissingEvidence:
    def test_dropped_fact_is_missing(self) -> None:
        w = _window_with(
            [
                ("s1", "system", "You are a precise assistant."),
                ("s2", "tool_result", "log 2: alpha bravo charlie delta"),
                ("s3", "tool_result", "log 3: echo foxtrot golf hotel"),
                ("s4", "conversation", QUESTION),
            ]
        )
        q = w.spans[-1]
        assert missing_evidence(w, q) == {"vault", "code", "room", "4"}

    def test_live_fact_is_not_missing(self) -> None:
        w = _window_with(
            [
                ("s1", "system", "You are a precise assistant."),
                ("s2", "conversation", FACT),
                ("s3", "conversation", QUESTION),
            ]
        )
        assert missing_evidence(w, w.spans[-1]) == set()

    def test_statement_turn_own_value_not_phantom(self) -> None:
        # A declarative fact turn whose answer number exists nowhere else:
        # missing by definition (own span excluded) - the grounding gate in
        # readmit_plan, not missing_evidence, keeps this case silent.
        w = _window_with(
            [
                ("s1", "system", "system prompt body"),
                ("s2", "conversation", FACT),
            ]
        )
        assert missing_evidence(w, w.spans[-1]) == {"1", "vault", "code", "room", "4", "1051"}


class TestReadmitPlan:
    def _archive_view(self, ap: Aperture, sid: str):
        from aperture.store import ArchiveView

        return ArchiveView(ap.store, sid)

    def test_empty_archive_never_fires(self) -> None:
        ap = Aperture()
        w = _window_with([("s1", "conversation", QUESTION)])
        assert readmit_plan(w, self._archive_view(ap, "x")) == []

    def test_no_grounding_is_silent(self) -> None:
        # Phantom-miss guard: the archive holds content, but nothing that
        # grounds the missing tokens -> no op.
        ap = Aperture()
        ap.store.archive_put("s", "a1", "conversation", "log: alpha bravo charlie", 0, 20)
        w = _window_with(
            [
                ("s1", "system", "system prompt body"),
                ("s2", "conversation", FACT),  # archived? no: live, but ids differ
            ]
        )
        # Archive content shares no salient token with the fact turn.
        assert readmit_plan(w, self._archive_view(ap, "s")) == []

    def test_digitless_grounding_is_silent(self) -> None:
        # Gate-2 precision (P3-2 regression): the archive shares the
        # template words but none of the missing NUMBERS - word-only
        # overlap must not manufacture evidence, the plan stays silent.
        ap = Aperture()
        ap.store.archive_put("s", "a1", "conversation", "routine check 1 ok", 0, 18)
        w = _window_with(
            [
                ("s1", "system", "system prompt body"),
                ("s2", "conversation", "routine check 0 ok"),
            ]
        )
        assert readmit_plan(w, self._archive_view(ap, "s")) == []

    def test_digit_grounding_still_fires(self) -> None:
        # Same shape, but the archived turn carries the missing number:
        # a genuine dangling reference fires.
        ap = Aperture()
        ap.store.archive_put("s", "a1", "conversation", "routine check 0 ok", 0, 18)
        w = _window_with(
            [
                ("s1", "system", "system prompt body"),
                ("s2", "conversation", "routine check 0 ok"),
            ]
        )
        ops = readmit_plan(w, self._archive_view(ap, "s"))
        assert len(ops) == 1 and ops[0].op == "semantic_retrieval"

    def test_fires_when_archive_grounds_missing_reference(self) -> None:
        ap = Aperture()
        ap.store.archive_put("s", "f1", "conversation", FACT, 0, len(FACT.encode()))
        w = _window_with(
            [
                ("s1", "system", "You are a precise assistant."),
                ("s2", "tool_result", "log: alpha bravo charlie delta"),
                ("s3", "conversation", QUESTION),
            ]
        )
        ops = readmit_plan(w, self._archive_view(ap, "s"))
        assert len(ops) == 1
        assert ops[0].op == "semantic_retrieval"
        assert ops[0].params["query"] == QUESTION

    def test_top_k_passthrough(self) -> None:
        ap = Aperture()
        ap.store.archive_put("s", "f1", "conversation", FACT, 0, 100)
        w = _window_with([("s1", "conversation", QUESTION)])
        ops = readmit_plan(w, self._archive_view(ap, "s"), top_k=7)
        assert ops[0].params["top_k"] == 7


class TestSessionIntegration:
    def _scenario(self, **ap_kwargs) -> tuple[Aperture, SpyGateway, str]:
        """Fact early, filler flood, question last; returns (ap, spy, reply)."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler

        spy = SpyGateway()
        ap = Aperture(model=spy, selector=HeuristicSelector(threshold=0.5, keep_n=6), **ap_kwargs)
        with ap.chat("readmit-t", token_budget=600) as chat:
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.ingest(FACT, role="user")
            for i in range(8):
                chat.ingest(make_filler(60, seed=i), role="tool")
            reply = chat.send(QUESTION)
        return ap, spy, reply

    def test_dropped_fact_is_readmitted_before_the_call(self) -> None:
        ap, spy, reply = self._scenario()
        final_window = spy.windows[-1]
        retrieved = [s for s in final_window.spans if s.span_class == "retrieved"]
        assert retrieved, "the archived fact must be re-admitted before the model call"
        assert any("1051" in s.content for s in retrieved)
        assert reply == "ok"  # SpyGateway echoes its fixed reply

    def test_stats_count_readmission(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler

        spy = SpyGateway()
        ap = Aperture(model=spy, selector=HeuristicSelector(threshold=0.5, keep_n=6))
        with ap.chat("readmit-stats", token_budget=600) as chat:
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.ingest(FACT, role="user")
            for i in range(8):
                chat.ingest(make_filler(60, seed=i), role="tool")
            chat.send(QUESTION)
            stats = dict(chat.stats())
        assert stats["readmits"] >= 1
        assert stats["readmit_spans"] >= 1

    def test_disabled_flag_restores_pre_p3_behavior(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler
        from eval.tasks import NeedleModel

        ap = Aperture(
            model=NeedleModel(),
            selector=HeuristicSelector(threshold=0.5, keep_n=6),
            proactive_readmit=False,
        )
        with ap.chat("readmit-off", token_budget=600) as chat:
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.ingest(FACT, role="user")
            for i in range(8):
                chat.ingest(make_filler(60, seed=i), role="tool")
            reply = chat.send(QUESTION)
        # The pre-P3 silent failure: fact dropped, no re-admission, the
        # deterministic model answers "unknown" (and a real model would
        # fabricate - docs/LIVE-FINDINGS.md).
        assert reply == "unknown"
        assert chat.stats()["readmits"] == 0

    def test_end_to_end_recovery_with_synthetic_needle_model(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler
        from eval.tasks import NeedleModel

        ap = Aperture(model=NeedleModel(), selector=HeuristicSelector(threshold=0.5, keep_n=6))
        with ap.chat("readmit-on", token_budget=600) as chat:
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.ingest(FACT, role="user")
            for i in range(8):
                chat.ingest(make_filler(60, seed=i), role="tool")
            reply = chat.send(QUESTION)
            stats = dict(chat.stats())
        assert reply == "1051"
        assert stats["readmits"] == 1
        assert stats["spans_dropped"] > 0

    def test_full_history_arm_never_readmits(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler
        from eval.tasks import NeedleModel

        ap = Aperture(model=NeedleModel(), profile="off")
        with ap.chat("readmit-off-profile", token_budget=600) as chat:
            chat.system("You are a precise assistant. Reply with the exact value only.")
            chat.ingest(FACT, role="user")
            for i in range(4):
                chat.ingest(make_filler(30, seed=i), role="tool")
            reply = chat.send(QUESTION)
            stats = dict(chat.stats())
        assert reply == "1051"  # nothing was ever dropped
        assert stats["readmits"] == 0
        assert stats["spans_dropped"] == 0

    def test_trace_ledger_records_the_readmit_diff(self) -> None:
        import sys
        import tempfile
        from pathlib import Path as P

        sys.path.insert(0, str(P(__file__).resolve().parents[1]))
        from aperture.trace.ledger import TraceLedger
        from eval.probes import make_filler
        from eval.tasks import NeedleModel

        with tempfile.TemporaryDirectory() as tmp:
            ledger = TraceLedger(P(tmp) / "trace.jsonl")
            ap = Aperture(model=NeedleModel(), ledger=ledger, profile="safe")
            with ap.chat("readmit-trace", token_budget=700) as chat:
                chat.system("You are a precise assistant. Reply with the exact value only.")
                chat.ingest(FACT, role="user")
                for i in range(16):
                    chat.ingest(make_filler(60, seed=i), role="tool")
                chat.send(QUESTION)
            recs = list(ledger.records())
        retrieval_diffs = [
            d for r in recs for d in r.diffs if d.op == "semantic_retrieval" and d.new_spans
        ]
        assert retrieval_diffs, "the trace must record the re-admission diff"
        assert all(n.span_id.startswith("ret-") for d in retrieval_diffs for n in d.new_spans)

    def test_selector_planned_retrieval_not_doubled(self) -> None:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from eval.probes import make_filler

        class RetrievalSelector(HeuristicSelector):
            def select(self, f) -> list[PlannedOp]:
                return [PlannedOp(op="semantic_retrieval", params={}, order=0)]

        spy = SpyGateway()
        ap = Aperture(model=spy, selector=RetrievalSelector())
        with ap.chat("readmit-dedup", token_budget=600) as chat:
            chat.system("You are a precise assistant.")
            chat.ingest(FACT, role="user")
            for i in range(8):
                chat.ingest(make_filler(60, seed=i), role="tool")
            chat.send(QUESTION)
            stats = dict(chat.stats())
        assert stats["readmits"] == 0  # the runtime skipped its proactive pass
