# Sprint 00 note (Phase P0 kickoff, weeks 1-2)

## Goal (spec Table 8, weeks 1-2)

Trace schema draft; eval harness skeleton; pip-installable skeleton wraps a
toy loop end to end.

## Shipped

- `bench/schema.py`: CurateBench trace schema **v1** (`curatebench/trace@v1`),
  strict, versioned, JSON Schema export; Appendix A example as executable test.
- `aperture/`: session types, interfaces (7.3), engine + guardrail,
  operators/keep_recent, heuristic selector, model gateways, ledger, probes,
  replay core, contracts (AG5), span store, runtime facade + `aperture.wrap`.
- `adapters/raw_loop.py`; `examples/toy_loop.py` (E2E demo).
- `eval/`: harness (manifest + append-only results), extended-NIAH probe,
  focused-vs-full probe, ConstraintRot probe, deterministic synthetic models.
- CI (ruff + pytest, py3.10-3.12), TDD throughout, Apache-2.0.

## Gate check (G1-G4 not due this phase)

- [x] Schema versioned from day one (P0 requirement, spec 7.4 closing note)
- [x] Toy loop wrapped end to end, trace parses against schema v1
- [ ] Context-rot replication on 3-4 real models (weeks 3-4) - harness ready,
      needs API budget
- [ ] ConstraintRot on 2 real models (weeks 5-6) - harness ready

## Decisions

- Stdlib-only gateway until P1 LiteLLM (keeps core deps = pydantic).
- Runtime `NewSpan` carries content; trace serializes bytes+provenance only
  (Appendix A fidelity preserved).
- Reward keeps `cache_invalidation` at runtime; trace derives it from
  `cache.invalidated_bytes` (Appendix A reward stays 4-field).
