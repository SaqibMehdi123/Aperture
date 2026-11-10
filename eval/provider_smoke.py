"""Live smoke test for the real provider keys (CI + local).

    python -m eval.provider_smoke

For each provider with a key in the environment (GROQ_API_KEY, GEMINI_API_KEY):

1. list the models the key can actually see,
2. pick one by preference order (exact ids or glob patterns),
3. send one tiny completion through Aperture's own LiteLLMGateway - this
   exercises the full stack (gateway -> provider -> Telemetry), not just the
   provider SDK,
4. print reply, token counts and latency.

Exit codes: 0 = every present key authenticated and answered (or was rate
limited, which still proves the key works); 1 = auth, region, catalog or
other hard failure. The network path only runs under `python -m`, so the
pytest suite stays offline.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from typing import Any

PREFERRED: dict[str, tuple[str, ...]] = {
    "groq": (
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gpt-oss-120b",
        "llama-*70b*",
        "gpt-oss-*",
        "llama-*instant*",
        "qwen*",
    ),
    "gemini": ("gemini-2.5-flash", "gemini-*-flash*", "gemini-*-flash-lite*"),
}
OPENAI_COMPAT_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
}
PROBE_PROMPT = "Reply with exactly: OK"


def _normalize(model_id: str) -> str:
    """Catalog ids sometimes carry a 'models/' prefix; match and report bare."""
    return model_id.removeprefix("models/")


def classify(exc: Exception) -> str:
    """Map a provider failure to a coarse category."""
    status = getattr(exc, "status_code", None)
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limited"
    if status == 404:
        return "missing_model"
    text = str(exc).lower()
    if "location" in text or "not supported" in text:
        return "region"
    return "other"


def pick_model(models: list[str], preferences: tuple[str, ...]) -> str | None:
    """First available model matching the preference order (globs allowed)."""
    got = pick_models(models, preferences, limit=1)
    return got[0] if got else None


def pick_models(
    models: list[str], preferences: tuple[str, ...], limit: int = 4
) -> list[str]:
    """Matched models in preference order (globs allowed, deduped, capped)."""
    normalized = [_normalize(m) for m in models]
    out: list[str] = []
    for pref in preferences:
        for model_id in normalized:
            if fnmatch.fnmatch(model_id, pref) and model_id not in out:
                out.append(model_id)
                if len(out) >= limit:
                    return out
    return out


def _list_models(provider: str, api_key: str) -> list[str]:
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url=OPENAI_COMPAT_BASE_URLS[provider],
        timeout=30,
    )
    return [m.id for m in client.models.list()]


def _probe(provider: str, model: str, api_key: str) -> dict[str, Any]:
    from aperture.models.litellm_gateway import LiteLLMGateway
    from aperture.session import Span, Window

    if provider == "gemini":
        # AI Studio's new AQ.-format keys authenticate as Bearer on the
        # OpenAI-compat route; litellm's native v1beta route rejects them and
        # serves a model list that disagrees with the compat catalog.
        model_string = f"openai/{model}"
        extra: dict[str, Any] = {"base_url": OPENAI_COMPAT_BASE_URLS["gemini"]}
    else:
        model_string = f"{provider}/{model}"
        extra = {}
    gateway = LiteLLMGateway(model_string, api_key=api_key, timeout_s=60, **extra)
    window = Window(
        token_budget=10_000,
        spans=[Span(span_id="s0", span_class="user", content=PROBE_PROMPT)],
    )
    response = gateway.complete(window)
    return {
        "text": response.text.strip(),
        "input_tokens": response.telemetry.input_tokens,
        "output_tokens": response.telemetry.output_tokens,
        "latency_ms": response.telemetry.latency_ms,
    }


def main() -> int:
    failures: list[str] = []
    for provider, env_var in (("groq", "GROQ_API_KEY"), ("gemini", "GEMINI_API_KEY")):
        api_key = os.environ.get(env_var)
        if not api_key:
            print(f"[{provider}] SKIP: {env_var} not set")
            failures.append(f"{provider}:no_key")
            continue
        try:
            models = _list_models(provider, api_key)
            candidates = pick_models(models, PREFERRED[provider])
            if not candidates:
                print(f"[{provider}] FAIL: no preferred model in catalog ({len(models)} listed)")
                print(f"[{provider}] catalog: {sorted(_normalize(m) for m in models)}")
                failures.append(f"{provider}:missing_model")
                continue
            sent = False
            for model in candidates:
                try:
                    result = _probe(provider, model, api_key)
                except Exception as exc:  # noqa: BLE001 - try the next candidate
                    kind = classify(exc)
                    if kind == "missing_model":
                        print(f"[{provider}] {model}: not served, trying next candidate")
                        continue
                    if kind == "rate_limited":
                        print(f"[{provider}] RATE_LIMITED (key authenticated) on {model}")
                        sent = True  # good enough: the key works
                        break
                    raise
                print(
                    f"[{provider}] OK {model}: reply={result['text']!r} "
                    f"in={result['input_tokens']}tok out={result['output_tokens']}tok "
                    f"latency={result['latency_ms']:.0f}ms"
                )
                sent = True
                break
            if not sent:
                print(f"[{provider}] FAIL: every candidate rejected ({candidates})")
                failures.append(f"{provider}:missing_model")
        except Exception as exc:  # noqa: BLE001 - report, don't crash the job
            kind = classify(exc)
            label = "RATE_LIMITED (key authenticated)" if kind == "rate_limited" else "FAIL"
            detail = str(exc)[:200]
            for attr in ("body", "details"):
                value = getattr(exc, attr, None)
                if value:
                    detail += f" {attr}={str(value)[:300]}"
            response = getattr(exc, "response", None)
            if response is not None:
                detail += f" response={getattr(response, 'text', '')[:300]}"
            print(f"[{provider}] {label}: {kind}: {detail}")
            if kind != "rate_limited":
                failures.append(f"{provider}:{kind}")

    if failures:
        print(f"SMOKE FAILED: {failures}")
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
