# Sprint 01 - Phase P1: Operator library, model-agnostic runtime, DX layer

Scope line (dossier Table 6, P1): *"Seven operators behind the Operator
protocol; LiteLLM gateway with cache telemetry; LangGraph + raw-loop
adapters; pinned store and protected-class metadata (AG2 groundwork); unit +
integration tests."* Plus one product requirement from the project owner:
**adoption must cost as little code as possible.**

## Shipped (8 small steps, TDD throughout)

| Commit | Delivered | Report anchor |
|---|---|---|
| 6d74aa3 | SQLite snapshot+archive store, protected-class registry (guardrail protects whole span classes) | P1 "pinned store and protected-class metadata" |
| 8807a25 | `dedupe` + `summarize` operators | P1 "seven operators" |
| 503a959 | `pin_protected` + `cache_align` + trace schema v2 (additive `diffs[].pinned[]`) | P1; AG1/AG2 groundwork |
| ce7e358 | `subagent_isolation` + `semantic_retrieval` (archive-backed) | P1; spec 6.5 |
| 67f3e62 | LiteLLM gateway, normalized cache telemetry, model-string resolution | P1 "LiteLLM gateway with cache telemetry" |
| 14d070c | `ChatSession` one-liner API, profiles, session stats | product DX requirement |
| f3bd527 | LangGraph adapter (per-thread state sync) | P1 "LangGraph ... adapters" |
| this one | Integration test (60-turn E2E), README quickstart, sprint note | P1 "unit + integration tests" |

## Evidence

`tests/test_integration_p1.py`, synthetic deterministic gateway, 60 turns,
4000-token budget:

- cumulative input tokens: 590,280 (full history) -> 190,055 (aperture
  balanced) = **67.8% reduction** (G1 target shape is >= 30%)
- prefix-cache hit rate **99.2%** from the stable system+constraint head
- constraint-survival probe passed on **100% of steps** (AG2)
- 173 spans dropped, all archived, retrieval round-trip verified
- 120/120 steps written as `curatebench/trace@v2` JSONL

## Design decisions

1. **DX first**: the flagship API is `ap.chat() -> chat.send(text)` (plain
   text in/out). System prompts are pinned+cache-headed and constraints are
   class-protected by default; outcomes join the trace automatically on
   context exit. Profiles ("lean"/"balanced"/"safe"/"off") are the only knob
   most users will ever touch. Power users keep `aperture.wrap()`.
2. **Trace schema v1 -> v2** (additive): non-destructive operators needed a
   logged annotation channel (`diffs[].pinned[]`) for pin/protect/cache-head
   flag changes. Per the spec's schema rule, any logged-field change bumps
   the version; v1 records still parse and the backward-compat test pins it.
3. **Nothing is ever really lost**: the runtime (not the operators) archives
   every dropped span into the store; operators stay pure. Retrieval reads a
   per-session `ArchiveView` injected via `Features.archive` (never
   serialized into traces).
4. **Purity kept**: subagent_isolation only describes the swap (drop + stub);
   archiving happens once, in `Session.complete()`.

## Definition-of-done check (spec 8.3)

- [x] code merged with unit + integration tests (135 tests green, ruff clean)
- [x] trace schema version bumped for the logged-field change (v2)
- [x] regression: full suite re-run per commit; integration numbers recorded
- [x] docs: README quickstart, CHANGELOG 0.2.0, sprint note

## Known follow-ups

- `semantic_retrieval` ships a lexical scorer; the embedder injection point
  (P4, AG-family) is the `SemanticRetrieval` constructor.
- Counterfactual replay of retrieval steps needs the archive handle restored
  from the store in the P3 replay harness (`Features.archive` is the hook).
- CrewAI adapter deliberately deferred (LangGraph covers the P1 line).
- The bandit selector (AG4) lands in P3 on top of the unchanged
  `PolicySelector` protocol.
