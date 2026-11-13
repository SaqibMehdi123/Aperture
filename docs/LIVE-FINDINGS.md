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
