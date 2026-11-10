"""Tests for eval.live: tolerant grading, routing, matrix planning, summary.

Everything here is offline and deterministic - the network path only runs
under `python -m eval.live`.
"""

from __future__ import annotations

from eval.live import DEFAULT_LIVE_ARMS, grade_live, plan_matrix, summarize_live
from eval.provider_smoke import API_KEY_ENV, gateway_route
from eval.tasks import build_task

NEEDLE = build_task("needle_qa", 0)
AGG = build_task("aggregate_batch", 0)
POLICY = build_task("policy_compliance", 0)


class TestGradeLiveNeedle:
    def test_exact_code(self) -> None:
        expected = NEEDLE.expected
        assert grade_live("needle_qa", NEEDLE, expected) is True

    def test_code_in_sentence(self) -> None:
        expected = NEEDLE.expected
        assert grade_live("needle_qa", NEEDLE, f"The access code is {expected}.") is True

    def test_wrong_code(self) -> None:
        wrong = "0000" if NEEDLE.expected != "0000" else "9999"
        assert grade_live("needle_qa", NEEDLE, wrong) is False

    def test_unknown(self) -> None:
        assert grade_live("needle_qa", NEEDLE, "unknown") is False

    def test_code_not_standalone(self) -> None:
        # a longer number containing the code is not a hit (word boundary)
        expected = NEEDLE.expected
        glued = f"9{expected}9"
        assert grade_live("needle_qa", NEEDLE, glued) is False


class TestGradeLiveAggregate:
    def test_bare_number(self) -> None:
        assert grade_live("aggregate_batch", AGG, AGG.expected) is True

    def test_number_in_sentence(self) -> None:
        assert grade_live("aggregate_batch", AGG, f"The total is {AGG.expected} units.") is True

    def test_wrong_number(self) -> None:
        wrong = f"{float(AGG.expected) + 5.0:.1f}"
        assert grade_live("aggregate_batch", AGG, wrong) is False

    def test_unknown(self) -> None:
        assert grade_live("aggregate_batch", AGG, "unknown") is False


class TestGradeLivePolicy:
    def test_refusal_variants(self) -> None:
        for reply in (
            "I cannot approve this refund.",
            "Sorry, I can't approve that.",
            "Unfortunately I am unable to approve the refund.",
            "This request must be refused per policy.",
        ):
            assert grade_live("policy_compliance", POLICY, reply) is True

    def test_approval_violation(self) -> None:
        assert grade_live("policy_compliance", POLICY, "The refund has been approved.") is False

    def test_unrelated_reply(self) -> None:
        assert grade_live("policy_compliance", POLICY, "Order 8812 noted.") is False


class TestGatewayRoute:
    def test_groq_native(self) -> None:
        assert gateway_route("groq", "qwen/qwen3.8-27b") == ("groq/qwen/qwen3.8-27b", {})

    def test_gemini_openai_compat(self) -> None:
        model_string, extra = gateway_route("gemini", "gemini-3-flash-preview")
        assert model_string == "openai/gemini-3-flash-preview"
        assert extra["base_url"].startswith("https://generativelanguage.googleapis.com")

    def test_unknown_provider(self) -> None:
        try:
            gateway_route("anthropic", "claude-x")
        except ValueError:
            return
        raise AssertionError("expected ValueError")

    def test_api_key_env_map(self) -> None:
        assert API_KEY_ENV["groq"] == "GROQ_API_KEY"
        assert API_KEY_ENV["gemini"] == "GEMINI_API_KEY"


class TestPlanMatrix:
    def test_deterministic_order_and_count(self) -> None:
        got = plan_matrix(DEFAULT_LIVE_ARMS, ("needle_qa",), (0, 1))
        assert got == [
            ("needle_qa", "full_history", 0),
            ("needle_qa", "full_history", 1),
            ("needle_qa", "keep_recent_tuned", 0),
            ("needle_qa", "keep_recent_tuned", 1),
            ("needle_qa", "aperture_fixed", 0),
            ("needle_qa", "aperture_fixed", 1),
        ]

    def test_total(self) -> None:
        assert len(plan_matrix(DEFAULT_LIVE_ARMS, ("a", "b", "c"), (0, 1))) == 18


class TestSummarizeLive:
    def _agg(self, success: float, tokens: int) -> dict:
        return {"success_rate": success, "input_tokens": tokens}

    def test_savings_and_parity(self) -> None:
        table = {
            "full_history": {"needle_qa": self._agg(1.0, 1000)},
            "aperture_fixed": {"needle_qa": self._agg(1.0, 400)},
            "keep_recent_tuned": {"needle_qa": self._agg(0.5, 700)},
        }
        out = summarize_live(table)
        assert out["aperture_fixed"]["needle_qa"]["savings_frac"] == 0.6
        assert out["aperture_fixed"]["needle_qa"]["success_equal_or_better"] is True
        assert out["keep_recent_tuned"]["needle_qa"]["success_equal_or_better"] is False

    def test_missing_full_history_baseline(self) -> None:
        out = summarize_live({"aperture_fixed": {"needle_qa": self._agg(1.0, 400)}})
        assert out["aperture_fixed"]["needle_qa"]["savings_frac"] == 0.0
        assert out["aperture_fixed"]["needle_qa"]["success_equal_or_better"] is False
