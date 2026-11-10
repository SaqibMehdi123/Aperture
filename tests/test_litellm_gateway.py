"""LiteLLM gateway: one model string -> any provider, with normalized cache
telemetry (spec Table 6 P1: "LiteLLM gateway with cache telemetry").

Tests inject a fake `litellm` module; no network, no keys. The gateway must
normalize both the Anthropic usage shape (cache_read_input_tokens) and the
OpenAI shape (prompt_tokens_details.cached_tokens) into the same Telemetry
the synthetic gateway produces, so the reward and the trace stay uniform.
"""

import sys
import types

import pytest
from aperture.models.gateway import SyntheticGateway
from aperture.session import Span, Window


class FakeUsage:
    def __init__(self, **kw):
        self.prompt_tokens = kw.get("prompt_tokens", 0)
        self.completion_tokens = kw.get("completion_tokens", 0)
        self.cache_read_input_tokens = kw.get("cache_read_input_tokens")
        self.cache_creation_input_tokens = kw.get("cache_creation_input_tokens")
        self.prompt_tokens_details = kw.get("prompt_tokens_details")
        self.cached_tokens = kw.get("cached_tokens")


class FakeResp:
    def __init__(self, usage):
        self.usage = usage

        class _Msg:
            content = "hello from the model"

        class _Choice:
            message = _Msg()

        self.choices = [_Choice()]


@pytest.fixture
def fake_litellm(monkeypatch):
    mod = types.ModuleType("litellm")
    mod.calls = []

    def completion(model=None, messages=None, **kw):
        mod.calls.append({"model": model, "messages": messages, **kw})
        return mod.next_response

    mod.completion = completion
    mod.completion_cost = lambda resp: 0.0123
    mod.next_response = FakeResp(FakeUsage(prompt_tokens=100, completion_tokens=20))
    monkeypatch.setitem(sys.modules, "litellm", mod)
    yield mod


def make_window():
    return Window(
        token_budget=32768,
        spans=[
            Span(span_id="sys", span_class="system", content="system prompt", cache_head=True),
            Span(span_id="u0", span_class="conversation", content="hello there"),
        ],
    )


def test_import_error_is_friendly(monkeypatch):
    monkeypatch.setitem(sys.modules, "litellm", None)  # forces ImportError
    import importlib

    import aperture.models.litellm_gateway as gw

    importlib.reload(gw)
    with pytest.raises(ImportError, match="aperture-runtime\\[litellm\\]"):
        gw.LiteLLMGateway("openai/gpt-4o-mini")


def test_anthropic_cache_shape_normalized(fake_litellm):
    fake_litellm.next_response = FakeResp(
        FakeUsage(prompt_tokens=100, completion_tokens=20, cache_read_input_tokens=80)
    )
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("anthropic/claude-sonnet-4-5", price_in_per_1k=3.0, price_out_per_1k=15.0)
    resp = gw.complete(make_window())
    assert resp.telemetry.input_tokens == 100
    assert resp.telemetry.output_tokens == 20
    assert resp.telemetry.prefix_tokens == 80
    assert resp.telemetry.cache_hit is True
    assert resp.telemetry.discount_usd == pytest.approx(80 / 1000 * 3.0 * 0.5)


def test_openai_cache_shape_normalized(fake_litellm):
    fake_litellm.next_response = FakeResp(
        FakeUsage(
            prompt_tokens=100,
            completion_tokens=20,
            prompt_tokens_details=FakeUsage(cached_tokens=60),
        )
    )
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("openai/gpt-4o-mini")
    resp = gw.complete(make_window())
    assert resp.telemetry.prefix_tokens == 60
    assert resp.telemetry.cache_hit is True


def test_no_cache_fields_means_miss(fake_litellm):
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("openai/gpt-4o-mini")
    resp = gw.complete(make_window())
    assert resp.telemetry.cache_hit is False
    assert resp.telemetry.prefix_tokens == 0
    assert resp.telemetry.discount_usd == 0.0


def test_uses_litellm_completion_cost(fake_litellm):
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("openai/gpt-4o-mini")
    resp = gw.complete(make_window())
    assert resp.telemetry.cost_usd == pytest.approx(0.0123)


def test_falls_back_to_price_list_when_completion_cost_fails(fake_litellm):
    def boom(resp):
        raise RuntimeError("unknown model pricing")

    fake_litellm.completion_cost = boom
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("openai/gpt-4o-mini", price_in_per_1k=2.0, price_out_per_1k=8.0)
    resp = gw.complete(make_window())
    assert resp.telemetry.cost_usd == pytest.approx(100 / 1000 * 2.0 + 20 / 1000 * 8.0, rel=1e-3)


def test_describe_splits_provider(fake_litellm):
    from aperture.models.litellm_gateway import LiteLLMGateway

    assert LiteLLMGateway("anthropic/claude-sonnet-4-5").describe() == (
        "anthropic",
        "anthropic/claude-sonnet-4-5",
    )
    assert LiteLLMGateway("bare-model-name").describe()[0] == "default"


def test_miss_after_hit_reports_invalidation_estimate(fake_litellm):
    from aperture.models.litellm_gateway import LiteLLMGateway

    gw = LiteLLMGateway("openai/gpt-4o-mini")
    fake_litellm.next_response = FakeResp(
        FakeUsage(
            prompt_tokens=100,
            completion_tokens=5,
            prompt_tokens_details=FakeUsage(cached_tokens=80),
        )
    )
    first = gw.complete(make_window())
    assert first.telemetry.cache_hit and first.telemetry.invalidated_bytes == 0
    fake_litellm.next_response = FakeResp(
        FakeUsage(prompt_tokens=100, completion_tokens=5)  # cache gone
    )
    second = gw.complete(make_window())
    assert second.telemetry.cache_hit is False
    assert second.telemetry.invalidated_bytes == 80 * 4  # 4 bytes/token estimate


def test_resolve_model_string_uses_litellm(fake_litellm):
    from aperture.runtime import Aperture

    rt = Aperture(model="openai/gpt-4o-mini")
    assert type(rt.model).__name__ == "LiteLLMGateway"


def test_resolve_model_passthrough_and_default():
    from aperture.runtime import Aperture, _resolve_model

    g = SyntheticGateway()
    assert _resolve_model(g) is g
    assert isinstance(_resolve_model(None), SyntheticGateway)
    rt = Aperture()
    assert isinstance(rt.model, SyntheticGateway)
