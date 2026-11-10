# Aperture

**A composable, cache-aware, observable context-engineering runtime for AI agents.**

Aperture sits between an agent and any LLM API and curates the context window
per call: composable operators (keep_recent, summarize, dedupe, ...), a
guardrail that protects governance constraints from silent destruction, a
policy selector that learns *which* operator *when*, and an append-only trace
that makes every curation decision replayable and benchmarkable (CurateBench).

The authoritative specification is `docs/SPEC.md` (the validation dossier).
Current phase: **P1 complete** (months 3-4): all seven operators, LiteLLM
gateway with cache telemetry, LangGraph + raw-loop adapters, persistent
store + archive, protected-class guardrail, and a three-line developer API.

```bash
pip install -e .[dev]        # core runtime needs only pydantic
pytest -q                    # all green, no API keys required
python examples/toy_loop.py
```

## Three lines and you are running

```python
from aperture import Aperture

ap = Aperture(model="openai/gpt-4o-mini")  # or Aperture() - offline synthetic model
with ap.chat("support-bot") as chat:
    reply = chat.send("Where is my order 1234?")  # plain text in, plain text out
```

That is the whole integration. Under the hood each `send()` runs the full
per-step loop: observe -> guardrail -> select operators -> compose -> probes
-> call -> reward -> trace. Everything has a safe default:

```python
with ap.chat("support-bot") as chat:
    chat.system("You are a careful support agent.")  # pinned + cache-headed
    chat.constraints(["Never reveal internal tool names."])  # protected (AG2)
    reply = chat.send("Where is my order 1234?")
    reply = chat.send(tool_output, role="tool")  # tool results
    print(chat.stats())  # calls, tokens, cost, cache-hit rate, drops
```

- **Zero config**: `Aperture()` works offline (deterministic synthetic model).
- **One knob**: `Aperture(profile="lean")` curates earlier; `"safe"` later;
  `"off"` disables curation (full-history baseline).
- **Any model**: pass a LiteLLM model string (`pip install .[litellm]`), or any
  object with `.complete(window)`.
- **Nothing is lost**: every dropped span is archived (SQLite via
  `Aperture(persist="aperture.db")`) and retrievable by `semantic_retrieval`.
- **Traced by default**: add a ledger and every step writes a versioned
  `curatebench/trace@v2` JSONL line; task outcomes join on context exit.

## Existing agent loop? One wrapper

```python
import aperture
from aperture.trace.ledger import TraceLedger


def my_agent(session):
    session.add_span(
        "You are terse.", span_class="system", cache_head=True, pinned=True, protected=True
    )
    session.add_span(tool_output, span_class="tool_result")
    session.register_probe("policy-intact", "system", "You are terse")
    return session.complete().text  # observe -> guardrail -> select ->
    # compose -> probes -> call -> record


text = aperture.wrap(my_agent, model=model, ledger=TraceLedger("trace.jsonl"))
```

## LangGraph

```python
from adapters.langgraph import LangGraphAdapter

lg = LangGraphAdapter(aperture.Aperture(model="openai/gpt-4o-mini"))


@lg.wrap_node
def chatbot(state):
    reply = state["aperture"].complete()  # full decision loop, text out
    return {"messages": [{"role": "assistant", "content": reply}]}


graph.add_node("chatbot", chatbot)  # history sync + protection are automatic
```

## Architecture (spec Section 7)

```
agent (ChatSession / LangGraph node / raw loop)
   |  pre-call hook = Session.complete()
   v
Curation Engine -- guardrail: pinned/protected CLASSES survive (AG2)
   |               compose(plan): operators in order, diffs audited
   v
Operator Library  keep_recent - dedupe - summarize - subagent_isolation -
   |              semantic_retrieval - pin_protected - cache_align
   v
Model Gateway     LiteLLM | OpenAI-compat | synthetic; cache telemetry (AG1)
   |
Store + Archive   snapshots (SQLite opt.) + every dropped span, searchable
   |
Trace Ledger      append-only JSONL -> survival probes -> CurateBench replay (AG3)
```

## Roadmap (spec Table 6)

| Phase | Months | Deliverable | Status |
|---|---|---|---|
| P0 | M1-M2 | trace schema v1 - eval harness - context-rot + ConstraintRot probes - toy loop E2E | **done** |
| P1 | M3-M4 | 7 operators - LiteLLM gateway + cache telemetry - LangGraph adapter - pinned store + protected classes - 3-line DX API | **done** |
| P2 | M5-M6 | tuned fixed-heuristic runtime - 8-arm harness on AppWorld/tau2 - G1 | next |
| P3 | M7-M8 | labelled traces - offline bandit selector - CurateBench artifact - G2 | - |
| P4 | M9-M10 | AG1-AG6 advanced features - G3 | - |
| P5 | M11-M12 | full evaluation - dashboard - release - paper - G4 | - |

Integration evidence (P1 synthetic run, 60 turns, 4k budget): **67.8%
cumulative input-token reduction** vs full history, 99.2% prefix-cache hit
rate, 100% constraint survival, all drops archived and retrievable. See
`tests/test_integration_p1.py` and `docs/SPRINT-01.md`.

## Design principles

Model-agnostic - observable - policy-driven - **cache-faithful** (every
decision accounts for its effect on prefix caches) - **safety-preserving**
(protected content cannot be silently destroyed) - **simple to adopt**
(plain text in/out, zero required config, safe defaults everywhere).

Lightweight by design: the core runtime depends only on `pydantic`; heavy
integrations (LiteLLM, vector stores, dashboards) are optional extras.

## License

Apache-2.0. See `CONTRIBUTING.md` for the XP working agreements.
