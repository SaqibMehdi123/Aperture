"""Survival probes v0 (AG2 groundwork, spec 7.1 "Observability + Trace Ledger").

A survival probe checks that protected content is still retrievable after a
curation decision. v0 uses deterministic containment (the pattern must appear
in a live span of the protected class); weeks 5-6 upgrade this to semantic
retrieval. Probes feed the trace `probes[]` group and the decay alerts (P4).
"""

from __future__ import annotations

from dataclasses import dataclass

from bench.schema import ProbeRecord

from aperture.session import Window


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    span_class: str
    pattern: str  # substring that must remain retrievable


@dataclass(frozen=True)
class ProbeOutcome:
    probe_id: str
    span_class: str
    survived: bool


def run_survival_probes(window: Window, specs: list[ProbeSpec]) -> list[ProbeOutcome]:
    out: list[ProbeOutcome] = []
    for spec in specs:
        survived = any(
            spec.pattern in s.content for s in window.spans if s.span_class == spec.span_class
        )
        out.append(ProbeOutcome(spec.probe_id, spec.span_class, survived))
    return out


def probe_records(outcomes: list[ProbeOutcome]) -> list[ProbeRecord]:
    return [
        ProbeRecord(**{"class": o.span_class, "probe": o.probe_id, "survived": o.survived})
        for o in outcomes
    ]
