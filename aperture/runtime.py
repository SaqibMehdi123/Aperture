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
from aperture.readmit import READMIT_TOP_K, readmit_plan
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
        self.stats = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "cache_hits": 0,
            "cache_misses": 0,
            "bytes_dropped": 0,
            "spans_dropped": 0,
            "probes_failed": 0,
            "readmits": 0,
            "readmit_spans": 0,
        }

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

        # P3-1 evidence-aware proactive re-admission: if the latest user turn
        # references entities/values the live window no longer grounds and the
        # archive holds dropped content that grounds them, restore the top
        # hits BEFORE the call. Keyed on evidence coverage, not on the model
        # admitting ignorance - real models guess instead of saying "unknown"
        # (docs/LIVE-FINDINGS.md, mechanically verified).
        if getattr(rt, "proactive_readmit", True) and not any(
            p.op == "semantic_retrieval" for p in plan
        ):
            ops = readmit_plan(
                composed, features.archive, top_k=getattr(rt, "readmit_top_k", READMIT_TOP_K)
            )
            if ops:
                composed, extra = rt.engine.compose(composed, ops, features)
                added = sum(len(d.new_spans) for d in extra)
                if added:
                    diffs.extend(extra)
                    self.stats["readmits"] += 1
                    self.stats["readmit_spans"] += added

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

        s = self.stats
        s["calls"] += 1
        s["input_tokens"] += resp.telemetry.input_tokens
        s["output_tokens"] += resp.telemetry.output_tokens
        s["cost_usd"] = round(s["cost_usd"] + resp.telemetry.cost_usd, 6)
        s["cache_hits" if resp.telemetry.cache_hit else "cache_misses"] += 1
        s["bytes_dropped"] += sum(d.bytes for diff in diffs for d in diff.dropped_spans)
        s["spans_dropped"] += sum(len(diff.dropped_spans) for diff in diffs)
        s["probes_failed"] += sum(not o.survived for o in outcomes)

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
                "plan": [{"op": p.op, "params": dict(p.params), "order": p.order} for p in plan],
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
            self.runtime.ledger.write_outcome(self.session_id, step, success, graded_at=_now_iso())


def _diff_dict(diff: DiffRecord) -> dict[str, Any]:
    return diff.model_dump()


PROFILES: dict[str, dict[str, int | float]] = {
    # "balanced" is the tuned fixed-heuristic point from `eval/tune.py`
    # (grid sweep on the deterministic task suite, train split; manifest in
    # results/tuning/): 53.1% cumulative input-token reduction vs full
    # history at equal task success and zero probe failures. "lean"/"safe"
    # are derived postures around that point, not independently tuned.
    "balanced": {"threshold": 0.5, "keep_n": 6, "dedupe_at": 0.2},
    "lean": {"threshold": 0.4, "keep_n": 5, "dedupe_at": 0.2},
    "safe": {"threshold": 0.7, "keep_n": 12, "dedupe_at": 0.4},
    "off": {"threshold": 1.01, "keep_n": 12},  # never curates (dedupe disabled)
}


class Aperture:
    """Runtime facade wiring model gateway, engine, selector, ledger, store.

    `model` accepts a model string ("openai/gpt-4o-mini", LiteLLM syntax; P1),
    any gateway object with `.complete(window)`, or None (deterministic
    synthetic gateway for tests/offline use).
    `persist` names a SQLite file for durable snapshots + archive; `store`
    accepts a pre-built store instance (takes precedence).
    `profile` is the one-knob curation posture: "balanced" (default),
    "lean", "safe", or "off"; an explicit `selector` overrides it.
    `proactive_readmit` (default True) enables the P3-1 evidence-aware
    re-admission: before each call, a dangling reference in the latest user
    turn (an entity/value no other live span grounds) whose evidence lives in
    the archive is restored via semantic_retrieval - so recovery never
    depends on the model admitting "unknown". `readmit_top_k` bounds the
    re-admission width (default 3).
    """

    def __init__(
        self,
        model: Any = None,
        ledger: TraceLedger | None = None,
        selector: PolicySelector | None = None,
        engine: CurationEngine | None = None,
        store: Any = None,
        persist: str | None = None,
        profile: str = "balanced",
        proactive_readmit: bool = True,
        readmit_top_k: int = READMIT_TOP_K,
    ) -> None:
        self.model = _resolve_model(model)
        self.proactive_readmit = proactive_readmit
        self.readmit_top_k = readmit_top_k
        self.ledger = ledger
        if selector is not None:
            self.selector = selector
        else:
            if profile not in PROFILES:
                raise ValueError(f"unknown profile {profile!r}; choose one of {sorted(PROFILES)}")
            self.selector = HeuristicSelector(**PROFILES[profile])
        self.engine = engine if engine is not None else CurationEngine()
        if store is not None:
            self.store = store
        elif persist is not None:
            from aperture.store import SqliteSpanStore

            self.store = SqliteSpanStore(persist)
        else:
            from aperture.store import SpanStore

            self.store = SpanStore()
        self._chat_counter = 0

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

    @contextmanager
    def chat(self, session_id: str | None = None, token_budget: int = 32768):
        """The one-liner API (spec 7.4): `with ap.chat() as chat: chat.send(...)`.

        Plain text in/out; system + constraints helpers; stats(); the task
        outcome joins the ledger automatically (success on clean exit, failure
        on exception).
        """
        from aperture.chat import ChatSession

        if session_id is None:
            session_id = f"chat-{self._chat_counter}"
        self._chat_counter += 1
        chat = ChatSession(self, session_id, token_budget)
        ok = True
        try:
            yield chat
        except Exception:
            ok = False
            raise
        finally:
            chat.finish(ok)

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
