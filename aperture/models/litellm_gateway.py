"""LiteLLM gateway: one model string -> any provider, with cache telemetry.

`pip install 'aperture-runtime[litellm]'` and pass "openai/gpt-4o-mini",
"anthropic/claude-sonnet-4-5", "gemini/gemini-2.5-pro", ... - LiteLLM handles
the provider differences; this gateway normalizes their usage reports into the
same Telemetry every other gateway produces:

- cache READS: Anthropic `cache_read_input_tokens`, OpenAI
  `prompt_tokens_details.cached_tokens` -> `prefix_tokens` + `cache_hit`
- cache MISSES after a previously-cached prefix -> `invalidated_bytes`
  (estimated at 4 B/token; the provider does not report bytes)
- cost: `litellm.completion_cost` when it knows the model, otherwise the
  caller-supplied price list

The dependency is optional: the core runtime stays stdlib-only and CI runs on
the synthetic gateway.
"""

from __future__ import annotations

import time
from typing import Any

from aperture.models.gateway import ModelResponse, Telemetry, _window_to_messages
from aperture.session import Window

BYTES_PER_TOKEN_ESTIMATE = 4


def _get(usage: Any, key: str, default: Any = None) -> Any:
    """Read a field off a dict-shaped or object-shaped usage report."""
    if usage is None:
        return default
    if isinstance(usage, dict):
        return usage.get(key, default)
    return getattr(usage, key, default)


def _cached_tokens(usage: Any) -> int:
    """Cache-read tokens across provider shapes (Anthropic / OpenAI)."""
    direct = _get(usage, "cache_read_input_tokens", 0) or 0
    if direct:
        return int(direct)
    details = _get(usage, "prompt_tokens_details", None)
    return int(_get(details, "cached_tokens", 0) or 0)


class LiteLLMGateway:
    """Uniform ModelGateway over LiteLLM model strings."""

    price_list = "litellm-archived"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        price_in_per_1k: float = 0.0,
        price_out_per_1k: float = 0.0,
        timeout_s: float = 120.0,
        cache_discount: float = 0.5,
        **completion_kwargs: Any,
    ) -> None:
        try:
            import litellm  # type: ignore
        except ImportError as exc:  # pragma: no cover - import path is env-dependent
            raise ImportError(
                "LiteLLMGateway needs the 'litellm' package. "
                "Install it with: pip install 'aperture-runtime[litellm]'"
            ) from exc
        self._litellm = litellm
        self.model = model
        self.api_key = api_key
        self.price_in = price_in_per_1k
        self.price_out = price_out_per_1k
        self.timeout_s = timeout_s
        self.cache_discount = cache_discount
        self._extra = completion_kwargs
        self._last_cached_tokens = 0

    def describe(self) -> tuple[str, str]:
        provider = self.model.split("/", 1)[0] if "/" in self.model else "default"
        return provider, self.model

    def complete(self, window: Window) -> ModelResponse:
        messages = _window_to_messages(window)
        kwargs: dict[str, Any] = {"timeout": self.timeout_s, **self._extra}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        start = time.perf_counter()
        resp = self._litellm.completion(model=self.model, messages=messages, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000.0

        usage = getattr(resp, "usage", None)
        input_tokens = int(_get(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(_get(usage, "completion_tokens", 0) or 0)
        cached = _cached_tokens(usage)
        cache_hit = cached > 0

        if cache_hit:
            invalidated = 0
            discount = cached / 1000.0 * self.price_in * self.cache_discount
            self._last_cached_tokens = cached
        else:
            # The prefix that was cached last call is now dead weight.
            invalidated = self._last_cached_tokens * BYTES_PER_TOKEN_ESTIMATE
            discount = 0.0
            self._last_cached_tokens = 0

        cost = self._cost(resp, input_tokens, output_tokens)
        text = ""
        choices = getattr(resp, "choices", None) or []
        if choices:
            text = getattr(getattr(choices[0], "message", None), "content", "") or ""
        return ModelResponse(
            text=text,
            telemetry=Telemetry(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
                latency_ms=round(latency_ms, 3),
                prefix_tokens=cached,
                cache_hit=cache_hit,
                invalidated_bytes=invalidated,
                discount_usd=round(discount, 6),
            ),
        )

    def _cost(self, resp: Any, input_tokens: int, output_tokens: int) -> float:
        cost_fn = getattr(self._litellm, "completion_cost", None)
        if callable(cost_fn):
            try:
                return float(cost_fn(resp))
            except Exception:
                pass  # unknown model pricing: fall back to the price list
        return input_tokens / 1000.0 * self.price_in + output_tokens / 1000.0 * self.price_out
