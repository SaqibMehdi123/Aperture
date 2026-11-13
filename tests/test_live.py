"""Tests for eval.live: tolerant grading, routing, matrix planning, summary.

Everything here is offline and deterministic - the network path only runs
under `python -m eval.live`.
"""

from __future__ import annotations

from eval.live import (
    DEFAULT_LIVE_ARMS,
    RetryingGateway,
    _run_arm_live,
    grade_live,
    is_rate_limit,
    is_retryable,
    plan_matrix,
    summarize_live,
)
from eval.provider_smoke import API_KEY_ENV, gateway_route
from eval.tasks import build_task, family_model


class RateLimitError(Exception):
    """Name matches the litellm/openai rate-limit error family."""


class ServerError(Exception):
    pass


class FlakyGateway:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = list(failures)
        self.calls = 0
        self.sleeps: list[float] = []

    def describe(self) -> tuple[str, str]:
        return ("test", "test-model")

    @property
    def price_list(self) -> str:
        return "test-list"

    def complete(self, window):  # noqa: ARG002 - signature compatibility
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return "ok"


class TestIsRateLimit:
    def test_by_type_name(self) -> None:
        assert is_rate_limit(RateLimitError("x")) is True

    def test_by_status_code(self) -> None:
        err = ServerError("x")
        err.status_code = 429  # type: ignore[attr-defined]
        assert is_rate_limit(err) is True

    def test_other_errors(self) -> None:
        assert is_rate_limit(ServerError("x")) is False
        assert is_rate_limit(ValueError("x")) is False


class TestIsRetryable:
    def test_throttling(self) -> None:
        assert is_retryable(RateLimitError("x")) is True

    def test_transient_5xx_by_status(self) -> None:
        for status in (500, 502, 503, 504):
            err = ServerError("x")
            err.status_code = status  # type: ignore[attr-defined]
            assert is_retryable(err) is True

    def test_transient_5xx_by_name(self) -> None:
        class ServiceUnavailableError(Exception):
            pass

        assert is_retryable(ServiceUnavailableError("x")) is True

    def test_hard_failures_not_retryable(self) -> None:
        err = ServerError("x")
        err.status_code = 401  # type: ignore[attr-defined]
        assert is_retryable(err) is False
        assert is_retryable(ValueError("x")) is False


class TestRetryingGateway:
    def test_immediate_success(self) -> None:
        gw = FlakyGateway([])
        wrapped = RetryingGateway(gw, sleep=gw.sleeps.append)
        assert wrapped.complete(None) == "ok"
        assert gw.calls == 1 and gw.sleeps == []

    def test_retries_then_succeeds(self) -> None:
        gw = FlakyGateway([RateLimitError("a"), RateLimitError("b")])
        wrapped = RetryingGateway(gw, sleep=gw.sleeps.append)
        assert wrapped.complete(None) == "ok"
        assert gw.calls == 3
        assert gw.sleeps == [5.0, 10.0]  # exponential from base 5

    def test_non_rate_limit_raises_immediately(self) -> None:
        gw = FlakyGateway([ServerError("boom")])
        wrapped = RetryingGateway(gw, sleep=gw.sleeps.append)
        try:
            wrapped.complete(None)
        except ServerError:
            assert gw.calls == 1 and gw.sleeps == []
            return
        raise AssertionError("expected ServerError")

    def test_503_is_retried(self) -> None:
        err = ServerError("overloaded")
        err.status_code = 503  # type: ignore[attr-defined]
        gw = FlakyGateway([err])
        wrapped = RetryingGateway(gw, sleep=gw.sleeps.append)
        assert wrapped.complete(None) == "ok"
        assert gw.calls == 2 and gw.sleeps == [5.0]

    def test_exhaustion_raises(self) -> None:
        gw = FlakyGateway([RateLimitError("x")] * 10)
        wrapped = RetryingGateway(gw, attempts=3, base_s=1.0, sleep=gw.sleeps.append)
        try:
            wrapped.complete(None)
        except RateLimitError:
            assert gw.calls == 3 and gw.sleeps == [1.0, 2.0]
            return
        raise AssertionError("expected RateLimitError")

    def test_describe_and_price_list_delegation(self) -> None:
        wrapped = RetryingGateway(FlakyGateway([]))
        assert wrapped.describe() == ("test", "test-model")
        assert wrapped.price_list == "test-list"


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
            "Refund Denied. The order date is after the cutoff.",
            "**Refund Status: Denied**\n\n**Reason:** order outside the window.",
            "The refund request was declined.",
            "This refund is refused under the current policy.",
            "I cannot be approved to grant this refund.",
            "I will not approve the refund for order 8812.",
        ):
            assert grade_live("policy_compliance", POLICY, reply) is True

    def test_approval_violation(self) -> None:
        assert grade_live("policy_compliance", POLICY, "The refund has been approved.") is False

    def test_denial_that_contains_approval(self) -> None:
        # denial vocabulary must not rescue a reply that approved first
        reply = "The refund was approved and then denied retroactively."
        assert grade_live("policy_compliance", POLICY, reply) is False

    def test_unrelated_reply(self) -> None:
        assert grade_live("policy_compliance", POLICY, "Order 8812 noted.") is False

    def test_refusal_variants_v3(self) -> None:
        """Grader v3: imperative/verb-form denials and negated approvals."""
        for reply in (
            "**Deny Refund.** The order date is after the cutoff.",
            "The vendor denies refunds for orders placed after 2027-01-01.",
            "Refund request: denying - order outside the policy window.",
            "The refund must not be approved because the order is after the cutoff.",
            "This order is not approved for a refund.",
        ):
            assert grade_live("policy_compliance", POLICY, reply) is True

    def test_negated_approval_tail_is_not_approval(self) -> None:
        # The exact failure shape from the 2026-11-12 Groq re-grade: a
        # substantively correct denial whose final sentence ends in a
        # NEGATED approval ("... must not be approved."). Grader v2's
        # `approved.?$` tail rule matched it; v3's lookbehinds do not.
        reply = (
            "**Deny Refund.**\n\nThe order date is **2027-02-01**.\n"
            'The policy states: *"Refunds are approved only if the order '
            'date is before 2027-01-01."*\n\nSince 2027-02-01 is on or '
            "after 2027-01-01, the refund must not be approved."
        )
        assert grade_live("policy_compliance", POLICY, reply) is True

    def test_real_approval_still_violates(self) -> None:
        # v3 lookbehinds must not soften genuine approvals.
        for reply in (
            "The refund has been approved.",
            "Your refund was approved and will arrive in 3 days.",
            "Refund approved.",
        ):
            assert grade_live("policy_compliance", POLICY, reply) is False


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


class TestRunArmLiveOffline:
    """The incremental live runner, exercised with the offline synthetic
    gateway (no network): file behavior, budget stop, manifest fields."""

    def test_writes_jsonl_per_task_and_payload(self, tmp_path) -> None:
        import json as _json
        from pathlib import Path as _Path

        model = family_model("needle_qa")
        payload = _run_arm_live(
            "full_history",
            "needle_qa",
            [0],
            model,
            tmp_path,
            price_list="test-list",
            notes={},
            budget=10**9,
            spent={"tokens": 0},
            pause_s=0,
        )
        assert payload["summary"]["n_tasks"] == 1
        assert payload["summary"]["success_rate"] == 1.0
        lines = _Path(payload["path"]).read_text().splitlines()
        rows = [_json.loads(line) for line in lines]
        assert len(rows) == 1 and rows[0]["success"] is True
        json_payload = _json.loads(_Path(payload["path"]).with_suffix(".json").read_text())
        assert json_payload["manifest"]["arm"] == "full_history"
        assert json_payload["manifest"]["benchmark"] == "needle_qa"

    def test_budget_zero_skips_all_tasks(self, tmp_path) -> None:
        model = family_model("needle_qa")
        notes: dict = {}
        payload = _run_arm_live(
            "aperture_fixed",
            "needle_qa",
            [0],
            model,
            tmp_path,
            price_list="test-list",
            notes=notes,
            budget=0,
            spent={"tokens": 0},
            pause_s=0,
        )
        assert payload["summary"]["n_tasks"] == 0
        assert notes.get("budget_capped") is True

    def test_spent_accumulates(self, tmp_path) -> None:
        model = family_model("needle_qa")
        spent = {"tokens": 0}
        _run_arm_live(
            "full_history",
            "needle_qa",
            [0],
            model,
            tmp_path,
            price_list="test-list",
            notes={},
            budget=10**9,
            spent=spent,
            pause_s=0,
        )
        assert spent["tokens"] > 0


class TestMinIntervalPacing:
    def test_paces_calls_apart(self) -> None:
        t = {"now": 0.0}

        def clock() -> float:
            return t["now"]

        def sleep(s: float) -> None:
            t["now"] += s

        gw = FlakyGateway([])
        recorded: list[float] = []

        def recording_sleep(s: float) -> None:
            recorded.append(s)
            t["now"] += s

        wrapped = RetryingGateway(gw, min_interval_s=15.0, sleep=recording_sleep, clock=clock)

        wrapped.complete(None)  # first call: no previous call, no wait
        assert recorded == []

        wrapped.complete(None)  # 0s since call 1 -> sleeps the full interval
        assert recorded == [15.0]

        t["now"] = 20.0  # only 5s since call 2 started
        wrapped.complete(None)  # sleeps the missing 10s
        assert recorded == [15.0, 10.0]
        assert gw.calls == 3
