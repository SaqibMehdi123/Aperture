# Results tree (append-only)

Two kinds of runs land here, both with full manifests (git hash, aperture
version, model IDs, price list, timestamp) per spec 8.3:

- `results/probes/<suite>/snapshot-<timestamp>.json` - offline synthetic-probe
  snapshots written by `python -m eval.snapshot`. They verify harness wiring
  and reproduce the published *direction* of each failure mode at CI scale;
  they are not benchmarks.
- `results/<benchmark>/<arm>/run-<timestamp>.json` - harness arm runs via
  `eval.harness.run_arm`. Real-model 8-arm runs start in Phase P2.

Files are never overwritten or deleted; unfavorable results are committed
too. JSON contents are gitignored locally except via explicit `git add -f`
when freezing a milestone (e.g., gate evidence).
