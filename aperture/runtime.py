"""Runtime facade: the per-step decision loop as a developer-facing API
(spec 7.2). `aperture.wrap(agent_loop, model=...)` instruments any loop that
calls an LLM; the Session exposes the pre-call hook every framework adapter
reduces to.

Loop per `Session.complete()`:
    observe -> guardrail(select) -> compose -> probes -> call -> reward -> record
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from bench.schema import (
    SCHEMA_VERSIONED,
    DiffRecord,
    TraceRecord,
)

from aperture.engine import CurationEngine
from aperture.interfaces import PolicySelector, Reward
from aperture.models.gateway import ModelResponse, SyntheticGateway
from aperture.policy.fallback import HeuristicSelector
from aperture.session import (
    SPAN_TOOL_RESULT,
    Features,
    Span,
    Window,
    _features_dict,
)
from aperture.trace.ledger import TraceLedger
from aperture.trace.probes import (
    ProbeSpec,
    run_survival_probes,
)
from aperture.trace.replay import window_diff_to_record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _redundancy_score(window: Window) -> float:
    """Cheap duplicate-content ratio over non-head spans (0.0 = all unique)."""
    tail = [s for s in window.spans if not s.cache_head]
    if len(tail) < 2:
        return 0.0
    seen: set[str] = set()
    dup_bytes = 0
    total_bytes = 0
    for s in tail:
        total_bytes += s.bytes
        if s.content in seen:
            dup_bytes += s.bytes
        else:
            seen.add(s.content)
    if total_bytes == 0:
        return 0.0
    return round(dup_bytes / total_bytes, 4)


class Session:
    """One agent session: spans in, model calls traced."""

    def __init__(
        self,
        runtime: Aperture,
        session_id: str,
        token_budget: int,
    ) -> None:
        self.runtime = runtime
        self.session_id = session_id
        self.window = Window(token_budget=token_budget)
        self.arm = "aperture_fixed"
        self.task_phase = "explore"
        self._span_seq = 0
        self._recorded_steps: list[int] = []
        self.probe_specs: list[ProbeSpec] = []

    def add_span(
        self,
        content: str,
        span_class: str = "conversation",
        pinned: bool = False,
        protected: bool = False,
        cache_head: bool = False,
        span_id: str | None = None,
    ) -> Span:
        self._span_seq += 1
        span = Span(
            span_id=span_id or f"{self.session_id}-s{self._span_seq}",
            span_class=span_class,
            content=content,
            created_step=self.window.step,
            pinned=pinned,
            protected=protected,
            cache_head=cache_head,
        )
        self.window.spans.append(span)
        return span

    def register_probe(self, probe_id: str, span_class: str, pattern: str) -> None:
        self.probe_specs.append(
            ProbeSpec(probe_id=probe_id, span_class=span_class, pattern=pattern)
        )

    def features(self) -> Features:
        recent_floor = max(0, self.window.step - 5)
        tool_tokens = sum(
            s.tokens
            for s in self.window.spans
            if s.span_class == SPAN_TOOL_RESULT and s.created_step >= recent_floor
        )
        archive = None
        if self.runtime.store is not None:
            from aperture.store import ArchiveView

            archive = ArchiveView(self.runtime.store, self.session_id)
        return Features(
            budget_used_frac=round(self.window.used_frac(), 6),
            task_phase=self.task_phase,
            tool_output_tokens_recent=tool_tokens,
            redundancy_score=_redundancy_score(self.window),
            drift_score=0.0,  # drift detector lands in Phase P4 (AG4)
            prefix_hash=self.window.prefix_hash(),
            archive=archive,
        )

    def complete(self) -> ModelResponse:
        """One full per-step decision loop (spec 7.2 steps 1-6)."""
        rt = self.runtime
        features = self.features()  # 1 observe
        plan = rt.selector.select(features)  # 2 select (guardrail lives in engine)
        composed, diffs = rt.engine.compose(self.window, plan, features)  # 3 compose

        # Archive everything the plan dropped ("nothing is ever really lost"):
        # the pre-call window still holds the originals.
        if rt.store is not None:
            for diff in diffs:
                for drop in diff.dropped_spans:
                    src = self.window.find(drop.span_id)
                    if src is not None:
                        rt.store.archive_put(
                            self.session_id,
                            src.span_id,
                            src.span_class,
                            src.content,
                            self.window.step,
                            src.bytes,
                        )

        outcomes = run_survival_probes(composed, self.probe_specs)  # 4 probes
        resp = rt.model.complete(composed)  # 5 call

        survival_penalty = 0.0 if all(o.survived for o in outcomes) else 1.0
        reward = Reward(
            task_progress=0.0,  # task outcome is joined later (Appendix A)
            cost_delta_usd=resp.telemetry.cost_usd,
            cache_invalidation=resp.telemetry.invalidated_bytes,
            survival_penalty=survival_penalty,
            latency_ms=resp.telemetry.latency_ms,
        )
        rt.selector.update(reward)  # 6 reward (fixed arms ignore; bandit learns in P3)

        provider, model_id, price_list = rt.describe_model()
        step = self.window.step
        rec = TraceRecord(
            **{
                "schema": SCHEMA_VERSIONED,
                "step": step,
                "ts": _now_iso(),
                "session_id": self.session_id,
                "arm": self.arm,
                "model": {"provider": provider, "id": model_id, "price_list": price_list},
                "features": _features_dict(features),
                "plan": [
                    {"op": p.op, "params": dict(p.params), "order": p.order} for p in plan
                ],
                "diffs": [_diff_dict(window_diff_to_record(d)) for d in diffs],
                "cache": {
                    "prefix_tokens": resp.telemetry.prefix_tokens,
                    "hit": resp.telemetry.cache_hit,
                    "invalidated_bytes": resp.telemetry.invalidated_bytes,
                    "discount_usd": resp.telemetry.discount_usd,
                },
                "probes": [
                    {"class": o.span_class, "probe": o.probe_id, "survived": o.survived}
                    for o in outcomes
                ],
                "call": {
                    "input_tokens": resp.telemetry.input_tokens,
                    "output_tokens": resp.telemetry.output_tokens,
                    "cost_usd": resp.telemetry.cost_usd,
                    "latency_ms": resp.telemetry.latency_ms,
                },
                "reward": {
                    "task_progress": reward.task_progress,
                    "cost_delta_usd": reward.cost_delta_usd,
                    "survival_penalty": reward.survival_penalty,
                    "latency_ms": reward.latency_ms,
                },
            }
        )
        if rt.ledger is not None:
            rt.ledger.record(rec)
            self._recorded_steps.append(step)
        if rt.store is not None:
            rt.store.put(self.session_id, step, self.window)  # pre-call snapshot
        self.window = composed
        self.window.step = step + 1
        self.add_span(resp.text, span_class="assistant")
        return resp

    def finish(self, success: bool) -> None:
        """Join the task-level outcome to every step recorded this session
        (Appendix A `outcome` is a task-level grade joined after the run)."""
        if self.runtime.ledger is None:
            return
        for step in self._recorded_steps:
            self.runtime.ledger.write_outcome(
                self.session_id, step, success, graded_at=_now_iso()
            )


def _diff_dict(diff: DiffRecord) -> dict[str, Any]:
    return diff.model_dump()


class Aperture:
    """Runtime facade wiring model gateway, engine, selector, ledger, store.

    `model` accepts a model string ("openai/gpt-4o-mini", LiteLLM syntax; P1),
    any gateway object with `.complete(window)`, or None (deterministic
    synthetic gateway for tests/offline use).
    `persist` names a SQLite file for durable snapshots + archive; `store`
    accepts a pre-built store instance (takes precedence).
    """

    def __init__(
        self,
        model: Any = None,
        ledger: TraceLedger | None = None,
        selector: PolicySelector | None = None,
        engine: CurationEngine | None = None,
        store: Any = None,
        persist: str | None = None,
    ) -> None:
        self.model = _resolve_model(model)
        self.ledger = ledger
        self.selector: PolicySelector = selector if selector is not None else HeuristicSelector()
        self.engine = engine if engine is not None else CurationEngine()
        if store is not None:
            self.store = store
        elif persist is not None:
            from aperture.store import SqliteSpanStore

            self.store = SqliteSpanStore(persist)
        else:
            from aperture.store import SpanStore

            self.store = SpanStore()

    def describe_model(self) -> tuple[str, str, str]:
        describe = getattr(self.model, "describe", None)
        if callable(describe):
            provider, model_id = describe()
        else:
            provider, model_id = "unknown", "unknown"
        price_list = getattr(self.model, "price_list", "unarchived")
        return provider, model_id, price_list

    @contextmanager
    def session(self, session_id: str, token_budget: int = 32768):
        yield Session(self, session_id, token_budget)

    def wrap(
        self, agent_loop: Callable[[Session], Any], session_id: str, token_budget: int = 32768
    ) -> Any:
        """Wrap a plain agent loop: it receives a Session whose `complete()`
        goes through the full decision loop (spec 7.4, `aperture.wrap`)."""
        with self.session(session_id, token_budget) as sess:
            return agent_loop(sess)


def _resolve_model(model: Any) -> Any:
    """Model resolution (P1): a model string selects the LiteLLM gateway; any
    object with `.complete(window)` passes through; None -> synthetic gateway
    (deterministic, offline, CI-friendly)."""
    if model is None:
        return SyntheticGateway()
    if isinstance(model, str):
        from aperture.models.litellm_gateway import LiteLLMGateway

        return LiteLLMGateway(model)
    return model


def wrap(
    agent_loop: Callable[[Session], Any],
    *,
    model: Any = None,
    ledger: TraceLedger | None = None,
    selector: PolicySelector | None = None,
    session_id: str = "session-0",
    token_budget: int = 32768,
    persist: str | None = None,
) -> Any:
    """Module-level entry point (spec 7.4: `aperture.wrap(agent_loop)`)."""
    rt = Aperture(model=model, ledger=ledger, selector=selector, persist=persist)
    return rt.wrap(agent_loop, session_id=session_id, token_budget=token_budget)
