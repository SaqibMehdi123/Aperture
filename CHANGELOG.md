# Changelog

All notable changes to Aperture are documented here. Format based on
Keep a Changelog; versioning is SemVer.

## [0.2.0] - Phase P1 (Months 3-4)

### Added
- **One-liner DX API** (`aperture/chat.py`): `ap.chat()` / `ChatSession` -
  plain-text `send()` with user/tool/system roles, `system()` pinned into the
  cache head, `constraints()` protected by class, `stats()`, automatic task
  outcome join on context exit.
- **Curation profiles** (`balanced` | `lean` | `safe` | `off`): one knob for
  the curation posture; explicit selectors still override.
- **Six operators** behind the Operator protocol (all seven now shipped):
  `dedupe` (normalized duplicate removal), `summarize` (fold with provenance,
  injectable summarizer), `pin_protected` (class + heuristic flagging),
  `cache_align` (explicit cache-stable prefix, AG1), `subagent_isolation`
  (bulky outputs -> stubs), `semantic_retrieval` (archive-backed re-admission,
  lexical scorer).
- **Persistent store** (`aperture/store/`): `SqliteSpanStore` snapshots +
  content archive with lexical search; `ArchiveView` per-session handle;
  runtime archives every dropped span ("nothing is ever really lost").
- **Protected-class metadata** (`aperture/protection.py`, AG2 groundwork):
  the guardrail protects whole span classes (default: `constraint`) even when
  flags are unset.
- **LiteLLM gateway** (`aperture/models/litellm_gateway.py`): model-string
  resolution (`Aperture(model="openai/gpt-4o-mini")`), normalized cache
  telemetry across Anthropic/OpenAI usage shapes, cost via
  `litellm.completion_cost` with price-list fallback; optional `[litellm]`
  extra.
- **LangGraph adapter** (`adapters/langgraph.py`): `wrap_node` with per-thread
  sessions, state<->window sync (dict + LangChain-style messages), system
  messages auto-protected, cursor-based dedup.
- **Trace schema v2** (`curatebench/trace@v2`): additive
  `diffs[].pinned[]` flag annotations; v1 records still parse.
- Session stats (calls, tokens, cost, cache hit/miss, drops) and
  `Window.to_dict/from_dict` serialization.
- Integration test: 60-turn E2E - 67.8% input-token reduction vs full
  history, 99.2% cache-hit rate, 100% constraint survival, archive retrieval.

## [0.1.0] - Phase P0 (Months 1-2)

### Added
- CurateBench **trace schema v1** (`bench/schema.py`), versioned as
  `curatebench/trace@v1`, matching Appendix A of the validation dossier; JSON Schema
  export; strict (extra-forbid) parsing.
- Context Plane session types (`aperture/session.py`): `Span`, `Window`,
  `Features`/`SessionView`, `WindowDiff` with protected-class and cache-head metadata.
- Core interface contracts (`aperture/interfaces.py`): `Operator`, `PolicySelector`,
  `Reward`, `PlannedOp` per Section 7.3 of the spec.
- Curation Engine (`aperture/engine.py`): plan composition, guardrail that prevents
  destructive operators from dropping pinned/protected spans (AG2 groundwork).
- Operator library seed (`aperture/operators/`): registry + `keep_recent`.
- Fixed-heuristic selector seed (`aperture/policy/fallback.py`).
- Model gateway (`aperture/models/gateway.py`): `ModelGateway` protocol, deterministic
  `SyntheticGateway` with prefix-cache telemetry, minimal OpenAI-compatible gateway.
- Trace ledger (`aperture/trace/ledger.py`): append-only JSONL.
- Replay engine core (`aperture/trace/replay.py`): deterministic counterfactual replay;
  same plan reproduces a recorded step bit-identically (G2 groundwork).
- Survival probes v0 (`aperture/trace/probes.py`): containment-based constraint
  survival checks (AG2 groundwork).
- Context contracts (`aperture/contracts.py`, AG5 groundwork) and in-memory versioned
  span store (`aperture/store/`).
- Runtime facade (`aperture/runtime.py`): `aperture.wrap(agent_loop)` + Session
  facade - observe -> guardrail -> select -> compose -> call -> record loop.
- Raw-loop adapter (`adapters/raw_loop.py`).
- Eval harness skeleton (`eval/harness.py`): 8-arm registry, run manifests, append-only
  results tree.
- P0 probes (`eval/`): extended NIAH context-rot probe, LongMemEval-style
  focused-vs-full probe, ConstraintRot reproduction probe; deterministic synthetic
  probe models so CI needs no API keys.
- Toy loop example wrapped end to end (`examples/toy_loop.py`).
