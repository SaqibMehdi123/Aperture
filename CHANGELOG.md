# Changelog

All notable changes to Aperture are documented here. Format based on
Keep a Changelog; versioning is SemVer.

## [0.4.2] - Phase P3 continued (facts-marked suite posture, self-echo gate)

### Added
- **Prevention-vs-recovery measurement**: the offline needle_qa loop now
  declares its facts through the P3-2 DX API by default
  (`run_task(..., mark_facts=True)`; `TaskPlan.fact_turn_idxs`). Marked
  posture (seed 0, tuned profile): 14 calls / 10,166 input tokens; the
  pre-P3-2 loop (`mark_facts=False`, kept for the recovery-layer tests):
  18 calls / 9,826 tokens with one proactive re-admission. Prevention costs
  ~3% input tokens, removes 4 model round-trips (-22% calls) and all
  lexical-trigger dependence; the flag is arm-independent so both postures
  stay arm-fair. `eval.compare` manifests stamp the posture in `note`.

### Changed
- **Re-admission grounding gate: self-echo exclusion** (`aperture/readmit.py`):
  an archived span that is a verbatim copy of the turn being answered is no
  longer accepted as grounding evidence. Found by the facts-marked tests
  under ultra-aggressive curation (keep_n=1): dropped template turns
  ("Please process the next support case.") grounded the next identical
  turn, re-admitting noise. Honest token consequence: the phantom
  re-admissions had been *accidentally evicting* large tool spans from the
  recent-keep_n window (each inserted 3 small "retrieved" copies that
  displaced ~3 large spans), so removing them raises tuned-arm input tokens
  ~6-7% on policy/aggregate: savings -63/-61/-41 -> -57/-58/-38 under the
  marked posture (needle baseline also shifts: facts skip 4 round-trips).
  Success rates and trace coverage unchanged; G1 rehearsal still passes
  (min savings 38.3% >= 30%, success equal-or-better). The mechanism and
  the P4 follow-up (a principled eviction operator for large stale tool
  outputs) are documented in docs/LIVE-FINDINGS.md.
- Offline benchmark re-run under the marked posture: 1.00 success on all
  curation arms; manifest
  `results/compare/summary-20261114T165055.147314Z.json`.

## [0.4.1] - Phase P3 continued (declarative-fact protection)

### Added
- **Declarative-fact protection / `chat.facts([...])` DX API** (P3-2, the
  second live-findings direction): `ChatSession.fact(text)` / `facts([...])`
  mirror `constraints()` with one deliberate asymmetry - facts are
  `span_class="fact"` and pinned, so keep_recent overflow and every other
  destructive operator cannot drop them, but the pin is bounded by
  `Aperture(fact_pin_budget)` (default 16). When a new fact exceeds the
  budget the OLDEST facts are demoted in place (FIFO, recency wins - the
  same posture keep_recent encodes); demoted facts stay live and droppable,
  land in the archive on drop, and stay recoverable by the P3-1
  evidence-aware re-admission. Two tiers: constraints are protected by
  CLASS (absolute survival, governance text); facts are pinned under a
  BUDGET (bounded survival, declarative knowledge) - explicit pinning
  without bound would just re-price the session toward full history (risk
  R8). Projects needing absolute fact survival can register the class:
  `ap.engine.protected_classes.register("fact")`. Session stats gain
  `facts_added` / `fact_demotions`; demotion is visible in every pre-call
  window snapshot.

### Changed
- **Re-admission grounding gate tightened** (`aperture/readmit.py`): when
  the missing reference set contains numbers, an archive hit must now carry
  one of those numbers - word-only overlap on template vocabulary no longer
  grounds a trigger. This closes a verified phantom-fire: a new statement
  turn ("routine check 0 ok") matched dropped template turns ("routine
  check 1 ok") on words alone and re-admitted stale content. The live
  needle_qa trigger is unaffected (its archived fact carries the asked
  number). Offline regression re-run: every cell byte-identical to the
  P3-1 manifest at 1.00 tuned-arm success;
  `results/compare/summary-20261114T162419.594611Z.json`.

## [0.4.0] - Phase P3 start (evidence-aware proactive re-admission)

### Added
- **Evidence-aware proactive re-admission** (`aperture/readmit.py`, wired
  into `Session.complete()`): before every model call, the runtime checks
  whether the latest user turn references salient entities/values (numbers
  always, non-stopword words otherwise) that no other live span grounds, and
  whether the archive actually holds content grounding them. When both gates
  pass it re-admits the top archive hits (default `top_k=3`) through the
  normal `semantic_retrieval` operator - inside the guardrail, visible as a
  `semantic_retrieval` diff in the trace. This is the P3-1 fix for the
  live-verified parity break (docs/LIVE-FINDINGS.md): real models fabricate,
  echo filler, or reply empty instead of saying "unknown", so a retry keyed
  on "unknown" never fires; recovery now keys on evidence coverage instead
  of model honesty. `Aperture(proactive_readmit=False)` restores the
  pre-P3 behavior; `readmit_top_k` bounds the re-admission width. Session
  stats gain `readmits` / `readmit_spans`.
- **Grader v3** (`eval/live.py`): imperative/verb-form denials (`deny`,
  `denies`, `denying`) and negated approvals (`not (be) approv`) join the
  refusal vocabulary; the approval tail rule `approved.?$` now carries
  fixed-width negative lookbehinds so "must not be approved." endings are
  not read as approvals. Fixes the 2026-11-12 Groq re-grade finding where a
  substantively correct baseline denial ("**Deny Refund.** ... the refund
  must not be approved.") graded False on both patterns. Run manifests now
  stamp `grade_live v3`.

### Changed
- Offline benchmark (20 tasks x 3 families per arm, deterministic grading
  models): tuned arms keep 1.00 success while savings improve from
  −56/−58/−39% to **−63/−61/−41%** (needle/policy/aggregate vs full
  history) - the "unknown" retry round-trip is gone, so recovery costs zero
  extra model calls. Baseline arms byte-identical. Manifest:
  `results/compare/summary-20261113T173232.109068Z.json`.
- `tests/test_tasks.py` aggressive-recovery test now asserts the P3
  contract: success at baseline call count (`readmits >= 1`) instead of a
  paid retry call.

## [0.3.0] - Phase P2 (tuned selector + offline benchmark)

### Added
- **Cross-dispatch live aggregator** (`python -m eval.compare_live`, no
  network): re-aggregates the append-only `results/live` tree from disk -
  latest complete run per (provider, arm, family) cell, incomplete runs never
  shadow complete ones - and emits the same savings / G1-live headline per
  provider (min savings at equal-or-better success, partial grids flagged
  via cell coverage). Lets gap-fill retries compose into one final table
  without re-spending free-tier tokens.
- **Optional model pin on the live-eval workflow** (`model` dispatch input):
  free-tier capacity for the catalog-auto-picked preview model comes and
  goes; a retry can pin the model id that worked last instead of re-rolling
  the catalog pick.
- **Live real-model arm runs** (`python -m eval.live` + dispatchable
  `live-eval` workflow): the same uniform loop, arms, and append-only results
  tree as the offline comparison, but graded through a real provider gateway
  (Groq / Gemini free tiers via LiteLLM). Tolerant live grader (`grade_live`),
  model verification before run start (`verify_model`: retired catalog ids are
  skipped with one tiny probe), harness-owned 429 backoff (`RetryingGateway`),
  per-task incremental result writes (a provider-side death preserves every
  completed task), and an input-token budget cap (`--max-input-tokens`) that
  ends the run gracefully under free-tier daily limits.
- **Deterministic task suite** (`eval/tasks.py`): three task families -
  needle QA (fact retention), policy compliance (constraint survival), batch
  aggregation (recent-evidence retention) - 20 eval tasks each plus a held-out
  train split, exact programmatic grading, deterministic grading models, and
  one uniform agent loop with an archive retrieval retry on "unknown".
- **Offline selector tuner** (`python -m eval.tune`): 48-config grid sweep of
  the heuristic knobs under hard constraints (zero task failures, zero probe
  failures), objective = minimum cumulative input tokens; append-only
  manifests in `results/tuning/`.
- **Arm implementations** (`eval/arms.py`): re-measured ACON-style
  always-compress and Headroom-proxy strategies inside the selector protocol,
  plus the six offline arms; provider-native and learned arms excluded by
  design (API key / P3).
- **Comparison runner** (`python -m eval.compare`): 6 arms x 3 families x 20
  tasks with per-task trace coverage; append-only per-run files and summary
  in `results/compare/`.
- Session stat `probes_failed` (per-call survival-probe failures).
- `archive_search(..., span_class=...)` class filter on both stores, so a
  tool-output query can rank tool evidence over chat turns.
- **Live provider smoke** (`python -m eval.provider_smoke` + CI job): one tiny
  completion per provider through Aperture's LiteLLM gateway; CI runs it on
  every push to main using repo secrets. Exit 0 also covers rate limits (key
  authenticated), non-zero on auth/region/catalog failures.

### Changed
- **Tuned `balanced` profile shipped as default**
  (`threshold=0.5, keep_n=6, dedupe_at=0.2`): 53.1% cumulative input-token
  reduction vs full history on the train split at 100% task success and zero
  probe failures (was 21.3% with the P0-era default).
- `keep_recent(keep_n=0)` now drops all droppable spans (regression-fixed
  `[:-0]` slicing); the guardrail still vetoes protected drops.
- Task-loop retrieval re-admits each archived hit as its own span (merged
  re-admission cross-contaminated aggregate sums).
- **Live refusal grader vocabulary widened** (`grade_live`): Groq live runs
  produced compliant refusals phrased "Refund Denied"/"declined" that the
  cannot-approve-only regex under-credited; denied/declined/refused (word-
  bounded) and cannot/will-not + optional "be" + approved now count, while
  the approval-violation negative check still wins.
- **Live-eval findings note** (`docs/LIVE-FINDINGS.md`) + window-state replay
  probe (`scripts/needle_window_probe.py`): documents the verified needle_qa
  parity-break mechanism on real models (facts truncated -> models guess or
  echo filler instead of "unknown" -> retrieval retry never fires; archive
  ranking proven healthy), the aggregate baseline instability, and the P3
  directions (evidence-aware re-admission, declarative-fact protection).

### Offline results (see README "Results")
- `aperture_fixed`: 39-58% savings at 100% success, 100% of curation
  decisions logged (G1 rehearsal, offline).
- `acon_always_compress`: 95%+ savings at 0.37 success - the cautionary
  result motivating guardrailed curation.

## [0.2.1] - P1 hardening

### Added
- Offline probe snapshot CLI (`eval/snapshot.py`): runs the three
  deterministic probe suites (extended NIAH, focused-vs-full, ConstraintRot)
  and writes append-only snapshots with full manifests under
  `results/probes/` - the results tree now ships with real data.
- A pinned direction-check test covers the snapshot CLI (append-only guard,
  manifest fields, synthetic-model direction).

### Removed
- Internal sprint notes and the stale README copy (the history stays on
  `main`); README placeholder notes were replaced with captured example
  output.

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
- Eval harness (`eval/harness.py`): 8-arm registry, run manifests, append-only
  results tree.
- P0 probes (`eval/`): extended NIAH context-rot probe, LongMemEval-style
  focused-vs-full probe, ConstraintRot reproduction probe; deterministic synthetic
  probe models so CI needs no API keys.
- Toy loop example wrapped end to end (`examples/toy_loop.py`).
