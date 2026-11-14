# Aperture

**A context-engineering runtime that cuts agent token costs automatically — install it in three lines, point it at any model.**

[![CI](https://github.com/SaqibMehdi123/Aperture/actions/workflows/ci.yml/badge.svg)](https://github.com/SaqibMehdi123/Aperture/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)
![Version](https://img.shields.io/badge/version-0.3.0-green.svg)
![Code style](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)

## Overview

Agent sessions accumulate tool outputs, duplicates, and stale turns until the context window is mostly waste — and the provider-native fixes are locked to one vendor. Aperture sits between your agent and any LLM API and curates the window on every call: seven composable operators (trim, dedupe, summarize, archive, retrieve) chosen by a policy selector, a guardrail that makes governance constraints impossible to silently destroy, and prefix-cache-aware decisions that keep the cheap cached prefix stable. Every curation decision is logged to an append-only, replayable trace so its quality can be measured — that is the basis of CurateBench, the project's decision-level benchmark.

The design is specified end to end in [`docs/SPEC.md`](docs/SPEC.md) (a primary-source validation dossier). Core runtime depends only on `pydantic`; heavy integrations are optional extras.

## Quick look

```python
from aperture import Aperture

ap = Aperture(model="openai/gpt-4o-mini")
with ap.chat("support-bot") as chat:
    reply = chat.send("Where is my order 1234?")  # plain text in, plain text out
```

That is the whole integration. Safety is automatic: system prompts are pinned into the cache-stable prefix, and constraint text can never be dropped by any operator.

The same loop, observed end to end — real output of `python examples/toy_loop.py` (no API keys):

```text
$ python examples/toy_loop.py
assistant: 'ok'
trace records written: 1
schema:      curatebench/trace@v2
features:    budget_used_frac=1.0 redundancy=0.0
plan/diffs:  ['keep_recent'] dropped=18
cache:       hit=False prefix_tokens=17 discount_usd=0.0
probes:      [True]
```

Every model call produces one versioned trace line: the features the selector saw, the plan it chose, the per-operator diff, the cache state, and whether the governance probes survived.

## Table of contents

- [Why Aperture](#why-aperture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Usage](#usage)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Testing and linting](#testing-and-linting)
- [Results — P2 offline benchmark](#results--p2-offline-benchmark)
- [Research and reproducibility](#research-and-reproducibility)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)
- [Citation](#citation)
- [Contact](#contact)

## Why Aperture

| | Without Aperture | With Aperture |
|---|---|---|
| Context growth | Full history resent every call | Curated window; stale content dropped and archived |
| Governance | Constraints silently erased by compaction | Guardrail: protected content survives every operator (100% in tests) |
| Prompt caching | Prefix cache broken by reordering | Explicit cache-stable head; 99% hit rate in tests |
| Debuggability | Opaque middleware | Every decision is a versioned, replayable trace line |

In a 60-turn integration run (deterministic synthetic gateway, 4,000-token budget), Aperture used **67.8% fewer cumulative input tokens** than full history at equal step count, with a **99.2% prefix-cache hit rate** and **100% constraint survival**. You can reproduce this — see [Research and reproducibility](#research-and-reproducibility).

## Quick start

Prerequisites: Python **3.10–3.12** and `pip`. No API keys needed to start — without a model, Aperture uses a deterministic synthetic gateway.

```bash
git clone https://github.com/SaqibMehdi123/Aperture.git
cd Aperture
pip install -e ".[dev]"       # runtime + pytest + ruff
pytest -q                     # 171 tests, all green, no keys required
python examples/quickstart.py # see the loop run end to end
```

Expected: `pytest` prints `171 passed` in about a second; the quickstart prints two synthetic replies plus a `stats` dict.

To use a real model, install the optional LiteLLM extra and pass a model string:

```bash
pip install -e ".[litellm]"
```

```python
ap = Aperture(
    model="anthropic/claude-sonnet-4-5"
)  # or openai/gpt-4o-mini, gemini/gemini-2.5-pro, ...
```

## Configuration

Aperture has **no environment variables**. Everything is configured through the `Aperture(...)` constructor; provider keys go to your client or LiteLLM as usual.

| Option | Required | Description | Example |
|---|---|---|---|
| `model` | No | LiteLLM model string, any object with `.complete(window)`, or `None` (synthetic, offline) | `Aperture(model="openai/gpt-4o-mini")` |
| `profile` | No | Curation posture: `balanced` (default), `lean` (curate earlier), `safe` (curate later), `off` (never curate) | `Aperture(profile="lean")` |
| `ledger` | No | `TraceLedger` for append-only JSONL decision traces | `Aperture(ledger=TraceLedger("trace.jsonl"))` |
| `persist` | No | SQLite file for durable window snapshots + content archive | `Aperture(persist="aperture.db")` |
| `selector` | No | Custom `PolicySelector` (overrides `profile`) | see [`aperture/policy/fallback.py`](aperture/policy/fallback.py) |
| `engine` / `store` | No | Custom `CurationEngine` / store instance | see [`aperture/engine.py`](aperture/engine.py) |

What degrades without the optionals: no `ledger` — no trace files (curation still runs); no `persist` — the archive lives in memory only; no `litellm` extra — model strings are unavailable, pass a gateway object or use the synthetic model.

## Usage

### Conversational API (recommended)

```python
from aperture import Aperture

ap = Aperture(model="openai/gpt-4o-mini")

with ap.chat("support-bot") as chat:
    chat.system("You are a careful support agent.")  # pinned + cache-headed
    chat.constraints(["Never reveal internal tool names."])  # protected by class
    chat.facts(["The customer's plan is Enterprise, renewed 2027-01-15."])  # pinned under a budget

    reply = chat.send("Where is my order 1234?")
    reply = chat.send(tool_output, role="tool")  # user | tool | system
    print(chat.stats())
```

`chat.facts([...])` (P3-2) marks declarative knowledge the conversation will
need later. Facts are pinned so curation cannot drop them while they fit the
fact pin budget (`Aperture(fact_pin_budget=16)`); beyond the budget the
oldest facts are demoted FIFO - still archived, so the evidence-aware
re-admission restores them when a later turn references their content.
Constraints stay absolutely protected by class; facts are bounded on purpose:
pinning everything is just full-history pricing with extra steps.

`chat.stats()` returns cumulative counters, e.g.:

```python
{
    "calls": 2,
    "input_tokens": 789,
    "output_tokens": 2,
    "cost_usd": 0.002359,
    "cache_hits": 1,
    "cache_misses": 1,
    "bytes_dropped": 0,
    "spans_dropped": 0,
    "facts_added": 1,
    "fact_demotions": 0,
    "cache_hit_rate": 0.5,
}
```

On context exit the task outcome joins the trace automatically: success on a clean exit, failure on exception. `chat.raw` exposes the full `Session` (probes, window, spans) when you need it.

### Wrapping an existing agent loop

```python
import aperture
from aperture.trace.ledger import TraceLedger


def my_agent(session):
    session.add_span(
        "You are terse.", span_class="system", cache_head=True, pinned=True, protected=True
    )
    session.add_span(tool_output, span_class="tool_result")
    session.register_probe("policy-intact", "system", "You are terse")
    return session.complete().text


text = aperture.wrap(my_agent, model=model, ledger=TraceLedger("trace.jsonl"))
```

### LangGraph

```python
from adapters.langgraph import LangGraphAdapter

lg = LangGraphAdapter(ap)


@lg.wrap_node
def chatbot(state):
    reply = state["aperture"].complete()  # full decision loop, reply text out
    return {"messages": [{"role": "assistant", "content": reply}]}


graph.add_node("chatbot", chatbot)
```

History sync is automatic per thread: state messages become spans (system messages protected), returned messages the runtime already recorded are not duplicated. The adapter is duck-typed — dict and LangChain-style messages both work, and you do not need `langgraph` installed to test your node logic.

### The operator library

All seven operators live behind one protocol and are composed per call by the selector:

| Operator | Effect | Destructive? |
|---|---|---|
| `keep_recent` | Keep the cache head plus the N most recent droppable spans | Yes |
| `dedupe` | Drop whitespace/case-normalized duplicates, keep one occurrence | Yes |
| `summarize` | Fold oldest spans into one summary span with provenance | Yes |
| `subagent_isolation` | Swap bulky tool outputs for compact stubs; full body archived | Yes |
| `semantic_retrieval` | Re-admit relevant archived spans on demand | No |
| `pin_protected` | Flag constraint-like content pinned + protected | No |
| `cache_align` | Make the cache-stable prefix explicit (AG1) | No |

The engine's guardrail runs on every diff: pinned, protected, and protected-class spans (default class: `constraint`) can never be dropped, even by an adversarial operator.

## Architecture

```mermaid
flowchart TB
    A["Your agent<br/>ChatSession · LangGraph node · raw loop"] --> B["Session.complete()<br/>one pre-call hook"]
    B --> C["Curation Engine<br/>guardrail: protected classes survive"]
    C --> D["Operator library<br/>7 composable operators"]
    D --> E["Model gateway<br/>LiteLLM · OpenAI-compat · synthetic"]
    E --> F["Trace ledger<br/>append-only JSONL, versioned v2"]
    C -.-> S["Context store + archive<br/>snapshots · every dropped span"]
    F -.-> G["CurateBench replay (P3)"]
```

```text
aperture/            installable runtime package
├── chat.py          ChatSession: the one-liner API (ap.chat())
├── runtime.py       Aperture facade + Session per-step decision loop
├── engine.py        Curation Engine: plan composition + guardrail
├── interfaces.py    Operator / PolicySelector protocols (spec §7.3)
├── session.py       Span, Window, Features, WindowDiff
├── protection.py    protected-class registry (AG2 groundwork)
├── contracts.py     typed Context Contracts (AG5 groundwork)
├── operators/       the seven operators
├── policy/          fixed-heuristic selector (bandit lands in P3)
├── models/          gateways: synthetic, OpenAI-compat, LiteLLM
├── store/           snapshots + searchable archive (memory / SQLite)
└── trace/           ledger, survival probes, replay engine
adapters/            framework adapters (raw loop, LangGraph)
bench/               CurateBench trace schema (curatebench/trace@v2)
eval/                task suite + selector tuning + arm comparison (8-arm harness)
examples/            quickstart.py, toy_loop.py
tests/               171 pytest tests
docs/                SPEC.md (dossier), research notes
results/             append-only probe snapshots + eval runs (real data, see results/README.md)
```

## Tech stack

| Layer | Technology | Why |
|---|---|---|
| Runtime | Python 3.10–3.12, `pydantic` | Typed contracts, schema validation, minimal footprint |
| LLM access | LiteLLM (optional extra) | One model string for any provider; normalized usage/cache telemetry |
| Framework adapters | LangGraph (duck-typed), raw loops | No hard framework dependency |
| Persistence | SQLite (stdlib), in-memory default | Durable snapshots + archive with zero setup |
| Quality | pytest, ruff, GitHub Actions | 171 tests on all supported Python versions |

## Testing and linting

```bash
pytest -q                    # full suite, no API keys required
pytest tests/test_integration_p1.py -q   # the savings/safety integration run
python -m eval.tune          # re-run the selector sweep (append-only manifest)
python -m eval.compare       # re-run the 6-arm comparison (append-only results)
ruff check .                 # lint (must pass before merge)
ruff format --check .        # formatting
```

## Results — P2 offline benchmark

Six arms (of the eight registered; provider-native needs an API key, the learned bandit lands in P3) ran the identical agent loop over three deterministic task families — needle QA (fact retention), policy compliance (constraint survival), and batch aggregation (recent-evidence retention) — 20 tasks each, graded exactly. Every arm used the same store, archive, and grading; only selection differed. Since v0.4.2 the needle_qa loop declares its facts through the `chat.facts()` DX API (P3-2 posture, arm-fair); `run_task(..., mark_facts=False)` restores the pre-P3-2 loop. Manifest: `results/compare/summary-20261114T165055.147314Z.json`.

| Arm | Success | needle_qa | policy_compliance | aggregate_batch |
|---|---|---|---|---|
| `full_history` | 1.00 | 465,868 tok | 484,816 tok | 277,170 tok |
| `keep_recent_tuned` | 1.00 | −57% | −58% | −38% |
| `threshold_edit_compact` | 1.00 | −54% | −57% | −52% |
| `acon_always_compress` | **0.37** | −93% | −95% | −95% |
| `headroom_proxy` | 1.00 | −68% | −69% | −57% |
| `aperture_fixed` (shipped) | 1.00 | −57% | −58% | −38% |

Read this table honestly:

- **`acon_always_compress` is the cautionary result**: it saves 95%+ of tokens and fails 63% of tasks — compression without governance destroys the evidence tasks depend on. That is the failure mode the guardrail + archive + retrieval design exists to prevent, and why savings are only ever reported jointly with success.
- **`aperture_fixed` — the tuned heuristic that ships as the `balanced` profile — holds 100% task success with 38–58% savings and 100% of curation decisions logged** (trace coverage 1.0 on every arm). G1 rehearsal: ≥30% savings at equal-or-better success, offline. It matches `keep_recent_tuned` exactly because this suite contains no duplicate spans — the tuned dedupe knob never fires here.
- **P3-1 proactive re-admission (v0.4.0) made recovery free**: the runtime restores archived evidence *before* the model call whenever the latest turn references an entity/value no live span grounds (keyed on evidence coverage, not on the model admitting "unknown" — real models fabricate instead, per `docs/LIVE-FINDINGS.md`). On the pre-P3-2 loop that removed the "unknown" retry round-trip entirely at unchanged success.
- **P3-2 prevention vs recovery, measured (v0.4.2)**: on one needle task (seed 0, tuned profile), the marked posture uses **14 model calls at 10,166 input tokens**; the unmarked loop uses **18 calls at 9,826 tokens** (facts dropped, one proactive re-admission at the question). Prevention costs ~3% more input tokens — the facts ride in every window — but removes 4 model round-trips (−22% calls) and all dependence on the lexical trigger firing; on real providers the dropped round-trips dominate (quota, latency), which is why `mark_facts=True` ships as the default.
- **Why the tuned savings moved from −63/−61/−41 to −57/−58/−38**: the v0.4.1 grounding-gate fix (digit match + self-echo exclusion) stopped phantom re-admissions of template turns. Measured mechanism: each phantom re-admission inserted 3 small "retrieved" copies into the recent-`keep_n` window, evicting ~3 large tool spans — accidental aggressive eviction that lowered tokens while re-admitting noise. The gate is kept (same success, no noise in the trace); a principled eviction mechanism for large stale tool outputs is P4 territory. G1 rehearsal still passes: min savings 38.3% ≥ 30% at equal success, 100% traced.
- **`headroom_proxy` saves more than the shipped heuristic on this suite** (57–69%) by planning purely on tool load. Closing that gap with a learned selector is a concrete P3 target.
- Tuning: the shipped point `{threshold: 0.5, keep_n: 6, dedupe_at: 0.2}` won a 48-config grid sweep on held-out training tasks at 53.1% savings vs full history with zero task and zero probe failures ([`eval/tune.py`](eval/tune.py), manifests in [`results/tuning/`](results/README.md)).

These are synthetic-model figures on a deterministic suite — real-model AppWorld / tau2-bench runs are the remaining P2 item and need an API key.

## Live real-model validation — G1-live (Groq, grader v3 + P3-1 runtime)

The same uniform loop and arms, graded through a real provider (Groq `qwen3.8-27b` free tier, seed 0, `python -m eval.live`; manifests in `results/live/`, aggregate `results/compare/live-summary-20261113T175338.070964Z.json`):

| Arm | needle_qa | policy_compliance |
|---|---|---|
| `full_history` | 1.0 / 27,743 tok | 1.0 / 27,442 tok |
| `keep_recent_tuned` | **1.0** / 11,885 tok (−57%) | 1.0 / 13,117 tok (−52%) |
| `aperture_fixed` (shipped) | **1.0** / 10,841 tok (−61%) | 1.0 / 12,073 tok (−56%) |

**G1-live: min savings 37% at success parity YES.** The needle_qa cells were the live parity break (`docs/LIVE-FINDINGS.md` — real models fabricate instead of saying "unknown"); the P3-1 evidence-aware proactive re-admission closed it on real models: the runtime re-admitted the archived fact before the call in both truncation arms (4 readmits / 12 spans each) and both replied the exact needle value. Gemini cells predate this runtime and are the next live item. The next Groq/Gemini dispatch also runs under the v0.4.2 loop (facts marked via the DX API; 4 fewer round-trips per needle task).

## Research and reproducibility

**Problem.** Context-curation policies are evaluated only at the system level, so nobody can say whether a single curation decision (dropping *this* observation, summarizing *that* span) was right. Aperture's answer is CurateBench: every step logs features, plan, per-operator diffs, cache state, and probes to a versioned schema (`curatebench/trace@v2`, [`bench/schema.py`](bench/schema.py)), which a replay engine can re-run under alternative policies.

**Methodology.** The project follows a 12-month phased plan with four measurable gates (G1–G4), defined in [`docs/SPEC.md`](docs/SPEC.md) §8. The prior-work grounding for every design choice is mapped in [`docs/RESEARCH-NOTES.md`](docs/RESEARCH-NOTES.md).

**Reproducing the headline numbers.** The 67.8% / 99.2% / 100% figures come from a deterministic synthetic gateway (no network, no keys) and are pinned by tests:

```bash
pytest tests/test_integration_p1.py -v
```

Real-model 8-arm evaluation on AppWorld / tau2-bench subsets is the remaining Phase P2 item; results will land in the same append-only [`results/`](results/README.md) tree with full manifests.

## Roadmap

Phases and gates follow [`docs/SPEC.md`](docs/SPEC.md) Table 6.

- [x] P0 — trace schema v1, eval harness, context-rot + ConstraintRot probes, toy loop end to end
- [x] P1 — seven operators, LiteLLM gateway with cache telemetry, LangGraph adapter, SQLite store + archive, protected classes, `chat()` API
- [x] P2 — tuned fixed-heuristic selector, 8-arm harness on AppWorld/tau2 subsets, gate G1 (≥30% savings at equal accuracy)
  - [x] tuned selector shipped as the default `balanced` profile (53.1% train-split savings; [`eval/tune.py`](eval/tune.py))
  - [x] offline 6-arm comparison + G1 rehearsal passed (39–58% savings at equal success, 100% traced; [`eval/compare.py`](eval/compare.py))
  - [x] real-model live runs (Groq + Gemini free tiers, [`eval/live.py`](eval/live.py)): savings replicate at 36–60%; G1-live parity PASSES on Groq under the P3-1 runtime (min savings 36–37% at equal success)
- [ ] P3 — labelled traces, offline bandit selector, CurateBench artifact release, gate G2
  - [x] P3-1 evidence-aware proactive re-admission (live-verified: needle_qa parity 0.0 → 1.0 on Groq)
  - [x] P3-2 declarative-fact protection: `chat.facts([...])` DX API + bounded pin budget
  - [ ] live Gemini re-dispatch under the P3 runtime; tool-assisted aggregate tasks; trace collection + bandit selector
- [ ] P4 — advanced-gap features: cache-aware reward, decay alerts, online adaptation, context contracts, async scheduler (gate G3)
- [ ] P5 — full comparative evaluation, observability dashboard, release, paper (gate G4)

## Known limitations

- The [results table](#results--p2-offline-benchmark) is measured on the deterministic offline suite (synthetic grading models); formal G1 evidence requires real-model AppWorld / tau2-bench runs.
- The offline suite contains no duplicate spans, so the tuned selector's dedupe knob never fires there; arms 4 (provider-native) and 8 (learned bandit) are excluded by design (API key / P3).
- The selector is a tuned fixed heuristic; the learned bandit arrives in P3.
- `semantic_retrieval` uses a lexical scorer; an embedder injection point exists but no embedding model ships.
- The package is not yet on PyPI — install from source for now.
- CrewAI adapter and the observability dashboard are deferred (P2+/P5).

## Contributing

Aperture is built with XP practices — TDD, small conventional commits, CI green on `main`, and a definition of done that includes the trace-schema rule. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the working agreements and setup.

## License

[Apache-2.0](LICENSE).

## Citation

If you use Aperture or CurateBench in research, please cite the repository:

```bibtex
@software{aperture2026,
  author  = {Mehdi, Saqib},
  title   = {Aperture: A Context-Engineering Runtime for AI Agents},
  year    = {2026},
  url     = {https://github.com/SaqibMehdi123/Aperture}
}
```

## Contact

Maintainer: [Saqib Mehdi](https://github.com/SaqibMehdi123) — saqibmehdi234@gmail.com. Questions and issues go through [GitHub Issues](https://github.com/SaqibMehdi123/Aperture/issues).
