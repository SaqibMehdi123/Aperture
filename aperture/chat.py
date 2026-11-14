"""ChatSession: the three-line developer API (spec 7.4, DX surface).

The design rule is: plain text in, plain text out, zero required config.

    from aperture import Aperture

    ap = Aperture(model="openai/gpt-4o-mini")
    with ap.chat("support-bot") as chat:
        chat.system("You are a careful support agent.")
        chat.constraints(["Never reveal internal tool names."])
        reply = chat.send("Where is my order 1234?")     # curated + traced
        print(chat.stats())                              # what curation bought

Safety is automatic: system prompts land pinned/protected in the cache head,
constraint text is protected by class (AG2), developer-marked facts are
pinned under a budget (P3-2), every dropped span is archived, and task
outcomes join the trace on context exit. Power users drop to
`chat.raw` (the full Session) or `aperture.wrap()` when they need it.
"""

from __future__ import annotations

from aperture.runtime import Aperture, Session


class ChatSession:
    """A conversational face on the per-step decision loop."""

    def __init__(self, runtime: Aperture, session_id: str, token_budget: int = 32768) -> None:
        self._sess = Session(runtime, session_id, token_budget)
        self._finished = False

    # -- context assembly ---------------------------------------------------
    def ingest(self, text: str, role: str = "user") -> None:
        """Add a turn WITHOUT a model call (framework state sync).

        roles: "user" | "tool" | "assistant" | "system". Used by adapters to
        mirror an external conversation state into the window.
        """
        if role == "system":
            self.system(text)
            return
        span_class = {"user": "conversation", "tool": "tool_result", "assistant": "assistant"}.get(
            role
        )
        if span_class is None:
            raise ValueError(f"unknown role {role!r}; use 'user', 'tool', 'assistant', or 'system'")
        self._sess.add_span(text, span_class=span_class)

    def system(self, text: str) -> None:
        """System prompt: pinned, protected, and part of the cache head."""
        self._sess.add_span(text, span_class="system", pinned=True, protected=True, cache_head=True)

    def constraint(self, text: str) -> None:
        """One governance constraint; protected by class (AG2)."""
        self._sess.add_span(text, span_class="constraint", pinned=True, protected=True)

    def constraints(self, texts) -> None:
        for t in texts:
            self.constraint(t)

    def fact(self, text: str) -> None:
        """One declarative fact ("The access code for vault 7 is 1051.").

        Pinned so curation cannot drop it while it fits the fact pin budget
        (`Aperture(fact_pin_budget)`, default 16); beyond the budget the
        oldest facts are demoted and become droppable - still archived, so
        the evidence-aware re-admission can restore them when a later turn
        references them. Mirrors `constraints()`: explicit marking, one line
        per fact, no heuristics deciding what counts as knowledge.
        """
        self._sess.add_fact(text)

    def facts(self, texts) -> None:
        for t in texts:
            self.fact(t)

    # -- the one-call API -----------------------------------------------------
    def send(self, text: str, role: str = "user") -> str:
        """Add one turn and run the full decision loop; returns the reply text.

        role: "user" (default) | "tool" (tool output) | "system".
        """
        if role == "user":
            self._sess.add_span(text, span_class="conversation")
        elif role == "tool":
            self._sess.add_span(text, span_class="tool_result")
        elif role == "system":
            self.system(text)
        else:
            raise ValueError(f"unknown role {role!r}; use 'user', 'tool', or 'system'")
        return self._sess.complete().text

    # -- introspection --------------------------------------------------------
    def history(self) -> list[tuple[str, str]]:
        """(span_class, content) pairs for every live span."""
        return [(s.span_class, s.content) for s in self._sess.window.spans]

    def stats(self) -> dict:
        """Cumulative session stats: calls, tokens, cost, cache hits, drops."""
        out = dict(self._sess.stats)
        hits, misses = out.get("cache_hits", 0), out.get("cache_misses", 0)
        out["cache_hit_rate"] = round(hits / (hits + misses), 4) if (hits + misses) else 0.0
        return out

    def finish(self, success: bool = True) -> None:
        """Join the task outcome to every recorded step (idempotent)."""
        if not self._finished:
            self._sess.finish(success)
            self._finished = True

    @property
    def raw(self) -> Session:
        """Escape hatch: the underlying Session (spans, probes, ledger)."""
        return self._sess

    def __repr__(self) -> str:  # pragma: no cover - formatting only
        s = self._sess.stats
        return (
            f"<ChatSession {self._sess.session_id} "
            f"calls={s['calls']} in={s['input_tokens']} out={s['output_tokens']} "
            f"dropped={s['spans_dropped']}>"
        )
