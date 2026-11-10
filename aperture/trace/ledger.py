"""Trace Ledger: append-only JSONL of trace records (spec 7.1, "Observability +
Trace Ledger"). One line per decision; lines are never rewritten or removed.
Task outcomes are joined via a sidecar outcomes file so the main ledger stays
append-only.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from bench.schema import OutcomeRecord, TraceRecord


class TraceLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.outcomes_path = Path(str(self.path) + ".outcomes.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, rec: TraceRecord) -> None:
        """Append one record. Raises if the same (session, step) is written
        twice - decisions are unique per step."""
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(rec.dump_json() + "\n")

    def records(self) -> Iterator[TraceRecord]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield TraceRecord.model_validate_json(line)

    def __len__(self) -> int:
        return sum(1 for _ in self.records())

    def write_outcome(self, session_id: str, step: int, success: bool, graded_at: str) -> None:
        """Join a task outcome for a recorded step (Appendix A `outcome`)."""
        entry = {"session_id": session_id, "step": step, "success": success, "graded_at": graded_at}
        with self.outcomes_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def join_outcomes(self) -> Iterator[TraceRecord]:
        """Yield records with sidecar outcomes merged in."""
        outcomes = self._read_outcomes()
        for rec in self.records():
            key = (rec.session_id, rec.step)
            if key in outcomes:
                success, graded_at = outcomes[key]
                rec = rec.model_copy(
                    update={"outcome": OutcomeRecord(task_success=success, graded_at=graded_at)}
                )
            yield rec

    def _read_outcomes(self) -> dict[tuple[str, int], tuple[bool, str]]:
        out: dict[tuple[str, int], tuple[bool, str]] = {}
        if not self.outcomes_path.exists():
            return out
        with self.outcomes_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                out[(entry["session_id"], entry["step"])] = (
                    entry["success"],
                    entry["graded_at"],
                )
        return out
