"""P0 exit demo (weeks 1-2): the pip-installable skeleton wraps a toy loop
end to end, writes a versioned trace, and shows cache + governance telemetry.

Run:  python examples/toy_loop.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import aperture
from aperture.models.gateway import SyntheticGateway
from aperture.trace.ledger import TraceLedger


def toy_agent_loop(session) -> str:
    """A toy agent: system constraint, a burst of tool outputs, one model call."""
    session.add_span(
        "You are a terse research assistant. Cite span ids for every claim.",
        span_class="system",
        cache_head=True,
        pinned=True,
        protected=True,
    )
    session.register_probe("system-prompt-intact", "system", "terse research assistant")
    for i in range(30):
        session.add_span(
            f"tool output {i}: {'lorem ipsum dolor sit amet ' * 20}", span_class="tool_result"
        )
    session.arm = "aperture_fixed"
    response = session.complete()
    session.finish(success=True)
    return response.text


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ledger = TraceLedger(Path(tmp) / "toy.jsonl")
        text = aperture.wrap(
            toy_agent_loop,
            model=SyntheticGateway(),
            ledger=ledger,
            session_id="toy-001",
            token_budget=2000,  # small budget so keep_recent triggers
        )
        records = list(ledger.records())
        print(f"assistant: {text!r}")
        print(f"trace records written: {len(records)}")
        rec = records[0]
        print(f"schema:      {rec.schema_}")
        print(f"features:    budget_used_frac={rec.features.budget_used_frac} "
              f"redundancy={rec.features.redundancy_score}")
        print(f"plan/diffs:  {[p.op for p in rec.plan]} "
              f"dropped={sum(len(d.dropped) for d in rec.diffs)}")
        print(f"cache:       hit={rec.cache.hit} prefix_tokens={rec.cache.prefix_tokens} "
              f"discount_usd={rec.cache.discount_usd}")
        print(f"probes:      {[p.survived for p in rec.probes]}")


if __name__ == "__main__":
    main()
