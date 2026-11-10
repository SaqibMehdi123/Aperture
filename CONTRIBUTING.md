# Contributing to Aperture

Aperture is developed with **Extreme Programming (XP) practices**, aligned with the
working agreements in `docs/SPEC.md` (Section 8.3). The short version:

## Definition of done

A change is done when:

1. Code is merged with **unit and integration tests** (test-first, red -> green -> refactor).
2. The **trace schema version is bumped** if any logged field changed
   (`bench/schema.py`, `SCHEMA_VERSION`). The schema is a versioned contract:
   CurateBench, the replay engine, and decay alerts all consume it.
3. The affected operator/selector is re-run on the regression subset so savings and
   success deltas are visible the same day (once eval arms exist, Phase P2+).

## XP practices we follow

- **TDD**: write the failing test first. No behavior lands without a test that pins it.
- **Small releases**: short-lived work; commits are small and conventional
  (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). CI must be green on `main` at all times.
- **Simple design**: the lightest thing that works. Core runtime depends only on
  `pydantic`; heavyweight integrations (LiteLLM, vector stores) are optional extras.
- **Collective ownership / standards**: `ruff check .` must pass; Python 3.10+;
  type hints on public APIs.
- **Experiment hygiene**: every eval run writes a manifest (git hash, arm, benchmark,
  seeds, model IDs, price list) into `results/`; the results tree is append-only and
  unfavorable results are committed too.

## Sprints

Work runs in two-week sprints ending with a demo against the regression subset and a
one-page sprint note in `docs/SPRINT-<nn>.md` that explicitly checks the current
gate's criteria (G1-G4).

## Setup

```bash
pip install -e .[dev]
pytest -q        # all green before you start
ruff check .     # lint
```
