"""Tests for eval.provider_smoke: error classification and model picking.

The live network path is never exercised here - only the pure helpers, so
`pytest -q` stays offline.
"""

from __future__ import annotations

import pytest
from eval.provider_smoke import classify, pick_model

PREFERRED = {
    "groq": ("llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gpt-oss-120b"),
    "gemini": ("gemini-2.5-flash",),
}


class FakeAPIError(Exception):
    def __init__(self, status_code: int, message: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code


class TestClassify:
    def test_auth_errors(self) -> None:
        assert classify(FakeAPIError(401, "Invalid API Key")) == "auth"
        assert classify(FakeAPIError(403, "Forbidden")) == "auth"

    def test_rate_limit(self) -> None:
        assert classify(FakeAPIError(429, "Rate limit reached")) == "rate_limited"

    def test_missing_model(self) -> None:
        assert classify(FakeAPIError(404, "model not found")) == "missing_model"

    def test_region_block(self) -> None:
        err = Exception("User location is not supported for the API use.")
        assert classify(err) == "region"

    def test_other(self) -> None:
        assert classify(FakeAPIError(500, "server error")) == "other"
        assert classify(ValueError("boom")) == "other"


class TestPickModel:
    def test_prefers_first_available(self) -> None:
        models = ["gpt-oss-120b", "llama-3.3-70b-versatile", "whisper-large-v3"]
        assert pick_model(models, PREFERRED["groq"]) == "llama-3.3-70b-versatile"

    def test_falls_back_to_preference_order(self) -> None:
        models = ["gpt-oss-120b", "whisper-large-v3"]
        assert pick_model(models, PREFERRED["groq"]) == "gpt-oss-120b"

    def test_returns_none_when_nothing_usable(self) -> None:
        assert pick_model(["whisper-large-v3"], PREFERRED["groq"]) is None

    def test_glob_pattern_preference(self) -> None:
        # a trailing '*' matches model families, not just exact ids
        models = ["gemini-3.8-flash", "gemini-2.5-pro"]
        assert pick_model(models, ("gemini-*-flash*",)) == "gemini-3.8-flash"
        assert pick_model(models, ("gemini-2.5-flash",)) is None


@pytest.mark.parametrize(
    "status,expected",
    [(400, "other"), (402, "other"), (408, "other"), (503, "other")],
)
def test_classify_parametrized(status: int, expected: str) -> None:
    assert classify(FakeAPIError(status, "x")) == expected
