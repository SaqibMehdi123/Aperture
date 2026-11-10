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

Files are never overwritten or deleted; unfavorable results are committed
too. JSON contents are gitignored locally except via explicit `git add -f`
when freezing a milestone (e.g., gate evidence).
