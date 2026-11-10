# Aperture

**A composable, cache-aware, observable context-engineering runtime for AI agents.**

Aperture sits between an agent loop and any LLM API and curates the context
window per call: composable operators (keep_recent, summarize, dedupe, ...),
a guardrail that protects governance constraints from silent destruction,
a policy selector that learns *which* operator *when*, and an append-only
trace that makes every curation decision replayable and benchmarkable
(CurateBench).

The authoritative specification is `docs/SPEC.md` (the validation dossier).
Current phase: **P0** (months 1-2): trace schema v1 frozen, eval harness
skeleton, context-rot + ConstraintRot replication probes, toy loop wrapped
end to end.

```bash
pip install -e .[dev]   # core runtime needs only pydantic
pytest -q               # all green, no API keys required
python examples/toy_loop.py
```

## Wrap any agent loop

```python
import aperture
from aperture.models.gateway import OpenAICompatGateway

model = OpenAICompatGateway(
    endpoint="https://api.anthropic.com/v1", model="claude-sonnet-4-5",
    api_key="...", price_in_per_1k=0.003, price_out_per_1k=0.015,
)

def my_agent(session):
    session.add_span("You are terse.", span_class="system",
                     cache_head=True, pinned=True, protected=True)
    session.add_span(tool_output, span_class="tool_result")
    session.register_probe("policy-intact", "system", "You are terse")
    return session.complete().text     # observe -> guardrail -> select ->
                                       # compose -> probes -> call -> record

text = aperture.wrap(my_agent, model=model, ledger=TraceLedger("trace.jsonl"))
```

Every `complete()` writes one `curatebench/trace@v1` JSONL line: features the
selector saw, the plan it chose, per-operator diffs, cache state, survival
probes, reward, and (joined later) the task outcome.

## Architecture (spec Section 7)

```
agent loop (LangGraph / CrewAI / raw)
   │  pre-call hook = Session.complete()
   ▼
Curation Engine ── guardrail: pinned/protected spans survive (AG2)
   │               compose(plan): operators in order
   ▼
Operator Library  keep_recent · summarize · dedupe · semantic_retrieval ·
   │              subagent_isolation · pin_protected · cache_align
   ▼
Model Gateway     any provider; token + prefix-cache telemetry (AG1)
   │
Trace Ledger      append-only JSONL → survival probes → CurateBench replay (AG3)
```

## Roadmap (spec Table 6)

| Phase | Months | Deliverable | Status |
|---|---|---|---|
| P0 | M1-M2 | trace schema v1 · eval harness · context-rot + ConstraintRot probes · toy loop E2E | **in progress** |
| P1 | M3-M4 | 7 operators · LiteLLM gateway + cache telemetry · LangGraph/CrewAI adapters · pinned store | - |
| P2 | M5-M6 | tuned fixed-heuristic runtime · 8-arm harness on AppWorld/tau2 · G1 | - |
| P3 | M7-M8 | labelled traces · offline bandit selector · CurateBench artifact · G2 | - |
| P4 | M9-M10 | AG1-AG6 advanced features · G3 | - |
| P5 | M11-M12 | full evaluation · dashboard · release · paper · G4 | - |

## Design principles

Model-agnostic · observable · policy-driven · **cache-faithful** (every
decision accounts for its effect on prefix caches) · **safety-preserving**
(protected content cannot be silently destroyed).

Lightweight by design: the core runtime depends only on `pydantic`; heavy
integrations (LiteLLM, vector stores, dashboards) are optional extras.

## License

Apache-2.0. See `CONTRIBUTING.md` for the XP working agreements.
