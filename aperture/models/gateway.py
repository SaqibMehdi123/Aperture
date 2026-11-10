"""Model Interface: uniform calls to any provider with token + cache telemetry
(spec 7.1, "Model Interface"). P0 ships the protocol, a deterministic synthetic
gateway (CI needs no keys or network), and a minimal OpenAI-compatible gateway.
The LiteLLM gateway with normalized cache telemetry lands in Phase P1.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from aperture.session import Window

# Synthetic list prices (USD per 1k tokens) so cost math is exercised end to
# end; the real price list is archived per eval run (spec 9.2).
DEFAULT_PRICE_IN_PER_1K = 0.003
DEFAULT_PRICE_OUT_PER_1K = 0.015


@dataclass(frozen=True)
class Telemetry:
    """Realized call telemetry (Appendix A `call` + `cache`)."""

    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    prefix_tokens: int = 0
    cache_hit: bool = False
    invalidated_bytes: int = 0
    discount_usd: float = 0.0


@dataclass(frozen=True)
class ModelResponse:
    text: str
    telemetry: Telemetry


@runtime_checkable
class ModelGateway(Protocol):
    def complete(self, window: Window) -> ModelResponse:
        ...


class SyntheticGateway:
    """Deterministic gateway for tests, CI, and the P0 toy loop.

    Simulates provider prefix caching honestly: the head fingerprint decides
    hit/miss, hits earn a 90% discount on head tokens, and head changes are
    reported as invalidated bytes (AG1 economics, cheaply).
    """

    def __init__(
        self,
        price_in_per_1k: float = DEFAULT_PRICE_IN_PER_1K,
        price_out_per_1k: float = DEFAULT_PRICE_OUT_PER_1K,
        output_text: str = "ok",
    ) -> None:
        self.price_in = price_in_per_1k
        self.price_out = price_out_per_1k
        self.output_text = output_text
        self._last_head_fp: str | None = None
        self._last_head_bytes: int = 0

    def complete(self, window: Window) -> ModelResponse:
        input_tokens = window.total_tokens()
        head = window.head_spans()
        head_fp = window.head_fingerprint()
        head_tokens = sum(s.tokens for s in head)

        cache_hit = bool(head) and head_fp == self._last_head_fp
        if cache_hit:
            # Hit: head billed at 10% of list price -> 90% discount.
            billed_head = head_tokens * 0.1
            discount = head_tokens / 1000.0 * self.price_in * 0.9
            invalidated = 0
        else:
            # Miss: any previously-live head prefix is now dead bytes.
            billed_head = head_tokens
            discount = 0.0
            invalidated = self._last_head_bytes
        self._last_head_fp = head_fp
        self._last_head_bytes = sum(s.bytes for s in head)

        output_tokens = max(1, len(self.output_text) // 4)
        billed_input = input_tokens - head_tokens + billed_head
        cost = billed_input / 1000.0 * self.price_in + output_tokens / 1000.0 * self.price_out
        latency_ms = 1.0 + len(window.spans) * 0.1  # analytic stand-in, deterministic
        return ModelResponse(
            text=self.output_text,
            telemetry=Telemetry(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
                latency_ms=round(latency_ms, 3),
                prefix_tokens=head_tokens,
                cache_hit=cache_hit,
                invalidated_bytes=invalidated,
                discount_usd=round(discount, 6),
            ),
        )


class OpenAICompatGateway:
    """Minimal gateway for any OpenAI-compatible /chat/completions endpoint.

    Span -> message mapping: system spans become system messages; everything
    else becomes a user message (tool outputs tagged). Uses stdlib urllib so
    the core runtime stays dependency-light; LiteLLM replaces this in P1.
    """

    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        price_in_per_1k: float = 0.0,
        price_out_per_1k: float = 0.0,
        timeout_s: float = 60.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.price_in = price_in_per_1k
        self.price_out = price_out_per_1k
        self.timeout_s = timeout_s

    def complete(self, window: Window) -> ModelResponse:
        messages = _window_to_messages(window)
        payload = {"model": self.model, "messages": messages}
        req = urllib.request.Request(
            self.endpoint + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        latency_ms = (time.perf_counter() - start) * 1000.0

        usage = body.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        cached = int(
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
        )
        cost = (
            input_tokens / 1000.0 * self.price_in
            + output_tokens / 1000.0 * self.price_out
        )
        text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return ModelResponse(
            text=text,
            telemetry=Telemetry(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=round(cost, 6),
                latency_ms=round(latency_ms, 3),
                prefix_tokens=cached,
                cache_hit=cached > 0,
                discount_usd=round(cached / 1000.0 * self.price_in * 0.5, 6),
            ),
        )


def _window_to_messages(window: Window) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for span in window.spans:
        if span.span_class == "system":
            messages.append({"role": "system", "content": span.content})
        elif span.span_class == "tool_result":
            messages.append({"role": "user", "content": f"[tool output]\n{span.content}"})
        else:
            messages.append({"role": "user", "content": span.content})
    if not messages:
        messages.append({"role": "user", "content": ""})
    return messages


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
