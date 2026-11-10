# Changelog

All notable changes to Aperture are documented here. Format based on
Keep a Changelog; versioning is SemVer.

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
