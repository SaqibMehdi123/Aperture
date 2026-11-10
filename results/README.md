# Results tree (append-only)

Three kinds of runs land here, all with full manifests (git hash, aperture
version, model IDs, price list, timestamp) per spec 8.3:

- `results/probes/<suite>/snapshot-<timestamp>.json` - offline synthetic-probe
  snapshots written by `python -m eval.snapshot` (direction checks at CI
  scale; not benchmarks).
- `results/tuning/run-<timestamp>.json` - selector grid sweeps written by
  `python -m eval.tune` (full per-config table + winning params).
- `results/compare/summary-<timestamp>.json` plus
  `results/<family>/<arm>/run-<timestamp>.json` - the arm comparison written
  by `python -m eval.compare` (per-task rows with trace coverage).

All offline-suite numbers come from deterministic synthetic grading models;
they are not real-model benchmarks. Real-model AppWorld / tau2-bench runs
(Phase P2's remaining item) write into the same tree.

- `results/live/<family>/<arm>/run-<timestamp>.json[l]` plus
  `results/live/summary-<timestamp>.json` - real-model arm runs written by
  `python -m eval.live` (dispatchable `live-eval` workflow). Grading is
  `grade_live` (tolerant phrasing); `.jsonl` lines are flushed per task, so
  an interrupted run still carries its completed tasks.

First live run (2026-11-10, Gemini `gemini-3.1-flash-lite-preview`, free
tier): 4 of 6 tasks completed before sustained provider 503s ended the job;
the empty `aggregate_batch/full_history` jsonl marks the arm that never
started. Headline from the completed tasks: `aperture_fixed` cut input
tokens 59% at equal success on `policy_compliance`, but lost the needle-QA
answer at 60% savings - the first real-model evidence that aggressive
curation can cost accuracy, which the synthetic suite had not shown.

Files are never overwritten or deleted; unfavorable results are committed
too. JSON contents are gitignored locally except via explicit `git add -f`
when freezing a milestone (e.g., gate evidence).
