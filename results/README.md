# Results tree (append-only)

Every eval run writes `results/<benchmark>/<arm>/run-<timestamp>.json` with a
full manifest (git hash, arm, benchmark, seeds, model IDs, price list) per
spec 8.3. Files are never overwritten or deleted; unfavorable results are
committed too. JSON contents are gitignored locally except via explicit
`git add -f` when freezing a milestone (e.g., gate evidence).
