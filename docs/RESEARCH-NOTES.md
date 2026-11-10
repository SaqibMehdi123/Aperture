# Research notes: prior work Aperture builds on

Design choices are grounded in public repos and research; this file maps each
choice to its source so contributors can trace *why* the runtime looks this
way. Claimed numbers in the dossier are re-measured, never copied (spec 9).

## Directly informing the runtime design

- **Letta / MemGPT** (https://github.com/letta-ai/letta) - the memory-block
  model (typed, addressable units of context with policies) validates the
  Span/Window design of the Context Plane. Aperture differs by making the
  *curation decisions* first-class (diffs, plans, rewards) rather than the
  memory itself, and by explicitly excluding a cross-session memory store
  (spec 7.5).
- **Anthropic context editing + memory tool** -
  https://docs.anthropic.com/en/docs/build-with-claude/context-editing -
  provider-native clearing/compaction with reported large token reductions.
  Aperture re-implements the *strategy* model-agnostically (arm 3 in the
  eval) and uses provider-native tools only as fallback operators.
- **Anthropic prompt caching** -
  https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching and
  **OpenAI prompt caching** -
  https://platform.openai.com/docs/guides/prompt-caching - both price
  cached prefix tokens far below fresh tokens and both key the cache on an
  exact prefix. This is why AG1 exists: any reordering/rewrite of the head
  silently voids the discount. Hence `cache_head` spans, `head_fingerprint`,
  `cache_head_unchanged` in every diff, and the cache-adjusted reward.
- **LiteLLM** (https://github.com/BerriAI/litellm) - the model-agnostic
  gateway layer (Phase P1) normalizes provider usage/cache telemetry; the
  P0 `OpenAICompatGateway` is its minimal stdlib stand-in.

## Informing the evaluation design

- **Chroma, "Context Rot" (2025)** - accuracy degrades with input length for
  every tested model, independent of task difficulty; the extended-NIAH probe
  grid (depth x length) follows this protocol.
- **LongMemEval** (arXiv:2410.10813) - the focused-vs-full design isolates
  rot; `eval/context_rot.py::focused_vs_full_probe` mirrors it.
- **ACON** (arXiv:2510.00615) - context compression with 26-54% peak-token
  reduction; arm 5 re-implements the always-compress strategy.
- **Governance decay** (arXiv:2606.22528) - compaction silently erodes safety
  constraints (violation rate 0% -> 30-59%); the ConstraintRot probe and the
  engine guardrail + survival probes (AG2) answer it directly.
- **Kapoor et al. on leakage and reporting** - accuracy and cost are always
  reported jointly; manifests archive prices and seeds (spec 9.2).

## Interface lineage

- `Operator.apply(window, ctx, params) -> WindowDiff` follows the
  diff-plus-audit pattern of editing/compaction tools while keeping operators
  pure, which is what makes counterfactual replay (CurateBench) possible.
- `PolicySelector.select/update/fallback` matches the contextual-bandit
  literature (LinUCB / Thompson sampling, spec Table 5); the P0 heuristic is
  the mandatory safe fallback under uncertainty (AG4).
- `ContextContract` (AG5) is shaped by subagent-spawning practice
  (budgeted, class-restricted handoffs with TTL), comparable to MCP tool
  schemas but at context level.
