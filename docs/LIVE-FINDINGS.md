# Live-eval findings: why truncation arms lose parity on real models

P2 real-model validation (G1 rehearsal), Groq + Gemini free tiers, seed 0,
grader v1 unless noted. Aggregate source: `results/compare/live-summary-
20261111T142958.287475Z.json` (latest complete run per cell, append-only
tree). All numbers below are read from that file and the per-cell run records
- nothing is estimated.

## Headline

Token savings replicate on real models: **36-60% input-token reduction**
(keep_recent_tuned / aperture_fixed vs full_history). Parity does **not**
hold everywhere yet: `needle_qa` is a clean, provider-independent parity
break caused by truncation itself; `aggregate_batch` parity is not
assessable because even the full-history baseline fails on both providers;
`policy_compliance` holds (equal success at ~59% savings on Gemini).

## The grid (succ / input tokens / savings vs full_history)

| provider | arm | needle_qa | policy_compliance | aggregate_batch |
| --- | --- | --- | --- | --- |
| gemini | full_history | 1.0 / 24,275 / - | 1.0 / 26,410 / - | 0.0 / 54,276 / - |
| gemini | keep_recent_tuned | **0.0** / 9,711 / 60.0% | 1.0 / 10,682 / 59.6% | 0.0 / 21,022 / 61.3% |
| gemini | aperture_fixed | **0.0** / 9,711 / 60.0% | 1.0 / 10,889 / 58.8% | 0.0 / 22,795 / 58.0% |
| groq | full_history | 1.0 / 27,776 / - | 0.0 / 26,798 / - (grader v1) | 0.0 / 19,533 / - |
| groq | keep_recent_tuned | **0.0** / 11,310 / 59.3% | 1.0 / 13,454 / 49.8% | 0.0 / 12,216 / 37.5% |
| groq | aperture_fixed | **0.0** / 11,257 / 59.5% | 0.0 / 13,038 / 51.4% (grader v1) | 0.0 / 12,463 / 36.2% |

Groq policy cells: full_history replied a correct refusal ("**Refund
Denied** ...") that grader v1 did not recognize, and one run degenerated to
"Ref" under daily-quota stress; grader v2 (commit `3bc5f97`) fixes the
vocabulary, re-grade scheduled post-quota-reset.

## Root cause of the needle_qa break (mechanically verified)

Replayed the harness offline with window inspection
(`scripts/needle_window_probe.py`, deterministic model, same arms):

1. **The needle is dropped before the question arrives.** Facts occupy plan
   turns 1-4 of 17; filler logs flood the rest. At question time both
   truncation arms hold only 8 spans (system + last two log pairs +
   assistant filler) - **0/4 fact spans remain**. full_history holds 4/4 and
   answers correctly on both providers.
2. **The archive side is healthy.** `archive_search(top_k=3, conversation)`
   ranks the *asked* fact first for both arms; for `aggregate_batch` the
   asked `[batch 1] readings: ...` span also ranks first. The
   drop-archive-retrieve round trip works; the evidence is one search away.
3. **The break is the retry trigger, not the retrieval.** The uniform retry
   fires only on "unknown"-like replies. The synthetic models reply exactly
   "unknown" -> retry -> ingest hits -> correct answer (1051 / 274.5 in the
   replay). Real models instead **guess or derail** when the evidence is
   gone. Recorded live `final_reply` signatures:
   - `4098` (Gemini keep_recent_tuned, needle_qa) - a plausible-format
     fabrication (4-digit code, same range as the real codes);
   - `quebec whiskey forest bravo west papa delta kilo hotel xray river
     papa` (Groq aperture_fixed) - a verbatim echo of the most recent tool
     output (log 5 filler words);
   - `` (empty reply, Groq keep_recent_tuned);
   - `17` / `34` / `1313.7` / `40.0` / `3` (aggregate arms) - invented sums.
   None match the unknown-vocabulary, so the retrieval retry never fires and
   the archived fact is never re-admitted. Offline parity rests on the
   synthetic "unknown" convention and does not transfer.

## aggregate_batch: baseline instability, parity not assessable

`full_history` itself fails the latest run on both providers (Gemini 216.5
vs expected 274.5; Groq 27). An earlier Gemini baseline run answered 274.5
correctly - real models are unstable at summing five one-decimal floats from
context. Truncation arms additionally lose the batch data (probe: 0 batch
spans in window at question time), so no arm shows parity. Note for suite
design: a real agent would sum programmatically via a tool call; context-only
arithmetic is a weak signal for the G1 gate.

## policy_compliance: the strongest positive result

Constraint text enters as `span_class="constraint"`, pinned + protected
(`chat.constraints()`); the guardrail vetoes dropping it, so both truncation
arms keep the refusal rule and match baseline success on Gemini at ~59%
savings. This is the class-level protection mechanism
(`aperture/protection.py`) working exactly as designed - and the template
for the needle fix.

## P3 directions (in priority order)

1. **Fix the retry trigger, not the retrieval**: evidence-aware proactive
   re-admission - when a question references entities/values absent from the
   current window and the window has been truncated, run
   `archive_search` and ingest the top hits before answering. Does not
   depend on the model admitting ignorance (real models guess instead).
2. **Declarative-fact protection in the selector**: early declarative
   statements ("The answer to X is Y") are pinned or excluded from
   keep_recent overflow - bounded by a pin budget; or expose a
   `chat.facts([...])` DX API mirroring `constraints()` (explicit, cheap,
   consistent with the AG2 mechanism, but requires developers to mark facts).
3. **Thicken the live suite**: one seed per cell is thin; run seeds 0-1
   under grader v2, and add a diagnostic arm whose system prompt permits
   "I don't have that value in context" to measure how much of the break is
   trigger-shaped vs retrieval-shaped.
4. **Suite realism for aggregation**: prefer tool-assisted summation tasks
   over context-only arithmetic for the G1 gate.

## Status / follow-ups

- Groq policy re-grade under grader v2 scheduled (post-quota-reset, 00:05
  UTC). Coverage check skips cells already complete after 13:00Z.
- needle_qa / aggregate live break is the entry item for the P3 plan; the
  replay probe is reproducible offline (`python3 scripts/needle_window_probe.py`).

## Update 2026-11-13: P3-1 shipped, grader v3

- **P3-1 (direction 1) is implemented in the runtime**
  (`aperture/readmit.py` + `Session.complete()`): evidence-aware proactive
  re-admission before every call - dangling references in the latest user
  turn (salient tokens absent from every other live span) whose evidence the
  archive grounds are restored via `semantic_retrieval`, inside the
  guardrail and the trace. Recovery no longer depends on the model admitting
  ignorance. Offline effect: tuned arms hold 1.00 success while savings
  improve −56/−58/−39% -> −63/−61/−41% (the "unknown" retry round-trip is
  gone; `results/compare/summary-20261113T173232.109068Z.json`). The live
  arms now need a fresh dispatch to measure the same effect on real models -
  the synthetic "unknown" convention that produced the break above is no
  longer load-bearing for parity.
- **Grader v3** (`eval/live.py`): the 2026-11-12 re-grade showed the Groq
  full_history policy cell failing on a *correct* denial ("**Deny Refund.**
  ... must not be approved.") - "deny" was not in the v2 vocabulary and the
  `approved.?$` tail rule matched the negated ending. v3 adds
  imperative/verb-form denials and negates the tail rule via lookbehinds.
- Follow-up live turn needed: re-dispatch groq
  `arms=full_history,keep_recent_tuned,aperture_fixed;families=policy_compliance,needle_qa;seeds=0`
  under grader v3 + P3-1 runtime to (a) re-grade the baseline policy cell
  and (b) measure whether proactive re-admission closes the needle_qa
  parity break on real models.

## Update 2026-11-13 (later): LIVE VALIDATION - G1-live parity PASSES on Groq

Re-dispatched the same day under grader v3 + P3-1 runtime (commit `df1e513`,
workflow run 43474369342 + a keep_recent_tuned re-run after the blank-reply
guard, `4cfb449`). Aggregate:
`results/compare/live-summary-20261113T175338.070964Z.json`.

### The fresh Groq grid (succ / input tokens / savings)

| arm | needle_qa | policy_compliance |
| --- | --- | --- |
| full_history | 1.0 / 27,743 / - | 1.0 / 27,442 / - |
| keep_recent_tuned | **1.0** / 11,885 / 57.2% | 1.0 / 13,117 / 52.2% |
| aperture_fixed | **1.0** / 10,841 / 60.9% | 1.0 / 12,073 / 56.0% |

**G1-live headline: keep_recent_tuned min savings 37%, success parity YES;
aperture_fixed min savings 36%, success parity YES** (aggregate_batch cells
remain the 2026-11-11 runs: 0.0 vs 0.0, baseline instability as documented
above). needle_qa went 0.0 -> 1.0 on both truncation arms - the root cause
section above is now a historical record, not an open break.

### Mechanical evidence the fix fired on real models

Both tuned needle_qa cells show identical runtime stats: 18 calls,
36 spans dropped, **4 readmits / 12 re-admitted spans** - and the
aperture_fixed cell replied the exact needle value `1051` (previously a
fabricated `4098` / filler echo / empty). keep_recent_tuned's first run
replied EMPTY with the evidence present (same degenerate quirk as 2026-11-11);
the arm-fair blank-reply re-ask (commit `4cfb449`) recovered it on re-run
(19 calls = 18 + 1 re-ask, reply `1051`).

### Remaining for a full cross-provider claim

- Gemini needle_qa/policy cells are still the 2026-11-11 pre-P3 runs
  (parity NO there is stale, not current); a Gemini dispatch under the new
  runtime is the next live turn (tight free-tier RPM, needs its own window).
- aggregate_batch parity needs tool-assisted summation tasks (direction 4)
  before it can grade either arm meaningfully.

## Update 2026-11-15: P3-2 shipped (direction 2), grounding gate tightened

- **Direction 2 is implemented in the runtime**: `chat.facts([...])` /
  `Session.add_fact()` - facts are `span_class="fact"`, pinned under
  `Aperture(fact_pin_budget)` (default 16, FIFO demotion of the oldest
  facts beyond the budget). This is the prevention layer that pairs with
  P3-1's recovery layer: within budget, a marked fact never leaves the
  window at all (no archive round trip, no lexical-trigger dependence -
  the trigger cannot miss what was never dropped); beyond budget, the
  demoted fact flows through drop -> archive -> P3-1 re-admission as
  before. Direction 2's alternative form (selector-side automatic
  declarative-statement detection) stays on the watchlist - explicit
  marking keeps the decision honest and the API mirrors `constraints()`.
- **Grounding-gate precision fix found by the P3-2 tests**: P3-1's
  grounding gate could fire on template-word overlap alone - a new
  statement turn ("routine check 0 ok") matched dropped template turns
  ("routine check 1 ok") on words and re-admitted stale content, despite
  the module docstring's phantom-miss promise. The gate now requires a
  digit match when the missing reference set contains numbers. The
  validated live needle_qa trigger is unaffected (the archived fact
  carries the asked number); the offline regression re-run below confirms
  the tuned arms keep 1.00 success.
- Offline regression (6 arms x 3 families x 20 tasks, deterministic
  models): every cell byte-identical to the P3-1 manifest
  (summary-20261113T173232.109068Z.json) - tuned arms hold 1.00 success at
  -63/-61/-41% savings; the new aggregate manifest:
  `results/compare/summary-20261114T162419.594611Z.json`.

## Update 2026-11-15 (later): facts-marked suite posture + the pollution finding

With `chat.facts()` wired into the needle_qa loop (`run_task mark_facts=True`,
arm-fair) and the grounding gate further tightened (self-echo exclusion: an
archived verbatim copy of the turn being answered is not evidence), the
benchmark re-run surfaced a mechanism worth recording:

- **Phantom re-admissions were accidentally evicting large tool spans.**
  Before the fix, each phantom trigger inserted 3 small "retrieved" template
  copies into the window; keep_recent keeps the N most RECENT droppables, so
  those copies occupied recent slots and pushed ~3 large tool spans out.
  Lower tokens, noise content. Measured on policy seed 0 (tuned profile):
  old gate 14 calls / 9,532 tok / 3 readmits / 29 dropped; fixed gate 14
  calls / 10,222 tok / 0 readmits / 21 dropped. The fix is kept - same
  success, no noise in the trace - at the cost of ~6-7% tuned-arm input
  tokens on policy/aggregate (savings -63/-61/-41 -> -57/-58/-38 under the
  marked posture). A principled version of the accidental effect - an
  operator that evicts large, stale, never-referenced tool outputs - is
  P4 territory (tool_output_tokens_recent is already a selector feature).
- **Prevention vs recovery, measured on needle seed 0 (tuned)**: marked
  facts = 14 calls / 10,166 tok / 0 readmits; unmarked loop = 18 calls /
  9,826 tok / 1 readmit. Prevention is ~3% more input tokens but 4 fewer
  model round-trips and zero lexical-trigger dependence - on real providers
  the round-trips (quota + latency) dominate, so mark_facts=True ships as
  the default.
- G1 rehearsal after both changes: min savings 38.3% >= 30% at success
  parity, 100% traced (`results/compare/summary-20261114T165055.147314Z.json`).
- Next live dispatch runs under this loop: needle tasks spend 4 fewer calls
  (quota-relevant on free tiers) and the Gemini cells get their first
  P3-runtime measurement.
