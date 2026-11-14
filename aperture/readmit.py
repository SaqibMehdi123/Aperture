"""Evidence-aware proactive re-admission (P3-1).

Live-model finding (docs/LIVE-FINDINGS.md, mechanically verified): when
curation drops an early fact, real models do not admit ignorance - they
fabricate a plausible answer, echo stale filler, or reply empty. A retrieval
retry keyed on "unknown"-style replies therefore never fires on real models;
the failure is silent.

This module moves the re-admission decision INTO the runtime, before the
model call, keyed on evidence coverage rather than on model honesty:

    if the latest user turn references salient entities/values that the
    live window no longer grounds, and the archive actually holds content
    that grounds them, re-admit the top archive hits first.

The check is lexical and dependency-free (same tokenizer family as the
archive scorer). Salient = non-stopword words plus every number: numbers
are the critical dangling-reference class ("What is the total of batch 3?"
references batch 3 even when every other word is boilerplate, and fabricated
sums/codes are exactly how real models fail - findings items 1 and 3).

Two gates keep the trigger precise:

1. **Missing-reference gate**: a salient query token must be absent from
   every OTHER live span. The query span itself is excluded from coverage,
   so a token that only ever appeared in dropped content counts as
   dangling; tokens still grounded elsewhere do not.
2. **Grounding gate**: the archive must contain a span that lexically
   matches the missing tokens (same min_score as ingestion), and when the
   missing set contains NUMBERS, a grounding hit must contain one of those
   numbers. Numbers are the critical dangling-reference class, and the
   digit check is what keeps template-word overlap from manufacturing
   evidence: a statement turn whose own number is new ("routine check 0
   ok") finds only word-level matches in the archive ("routine check 1
   ok") and stays silent - the phantom-miss case. A question that genuinely
   references a dropped value ("the code for room 4?") finds the archived
   fact carrying that number and fires.

Cost bounds: at most one archive probe + one retrieval op per model call,
top_k re-admitted spans (default 3), and the operator never admits content
already live. Re-admitted spans are class "retrieved" with provenance
(`summary_of`), so the trace ledger records exactly what was restored.
"""

from __future__ import annotations

import re

from aperture.interfaces import PlannedOp
from aperture.session import Span, Window

READMIT_TOP_K = 3
READMIT_MIN_SCORE = 0.05

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Template/boilerplate vocabulary that is never evidence. Kept minimal and
# purpose-built: task-suite question templates ("Answer with the exact
# value only", "What is the total of batch N?") must not manufacture
# dangling references, while domain words (vault, code, room, refund,
# order, batch) stay salient.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "nor",
        "so",
        "yet",
        "if",
        "then",
        "than",
        "else",
        "when",
        "while",
        "because",
        "although",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "am",
        "be",
        "been",
        "being",
        "do",
        "does",
        "did",
        "done",
        "doing",
        "has",
        "have",
        "had",
        "having",
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "this",
        "that",
        "these",
        "those",
        "there",
        "here",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "from",
        "as",
        "into",
        "about",
        "over",
        "under",
        "after",
        "before",
        "between",
        "out",
        "up",
        "down",
        "off",
        "above",
        "below",
        "around",
        "through",
        "not",
        "no",
        "yes",
        "very",
        "too",
        "also",
        "just",
        "only",
        "please",
        "tell",
        "give",
        "say",
        "said",
        "show",
        "let",
        "question",
        "questions",
        "answer",
        "answers",
        "exact",
        "exactly",
        "value",
        "values",
        "number",
        "numbers",
        "total",
        "totals",
        "sum",
        "sums",
        "reading",
        "readings",
        "note",
        "noted",
        "log",
        "logs",
        "fact",
        "facts",
        "request",
        "requests",
    ]
)


def tokenize(text: str) -> set[str]:
    """Lowercased word/number tokens (same shape as the store's scorer)."""
    return set(_TOKEN_RE.findall(text.lower()))


def salient_tokens(text: str) -> set[str]:
    """Evidence-bearing tokens: numbers always, non-stopword words otherwise."""
    out: set[str] = set()
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok.isdigit() or len(tok) >= 2 and tok not in STOPWORDS:
            out.add(tok)
    return out


def latest_query_span(window: Window) -> Span | None:
    """The most recent conversation span - the turn about to be answered."""
    for span in reversed(window.spans):
        if span.span_class == "conversation":
            return span
    return None


def missing_evidence(window: Window, query_span: Span) -> set[str]:
    """Salient query tokens not grounded by any OTHER live span."""
    salient = salient_tokens(query_span.content)
    if not salient:
        return set()
    covered: set[str] = set()
    for s in window.spans:
        if s.span_id != query_span.span_id:
            covered |= tokenize(s.content)
    return salient - covered


def readmit_plan(
    window: Window,
    archive,
    top_k: int = READMIT_TOP_K,
    min_score: float = READMIT_MIN_SCORE,
) -> list[PlannedOp]:
    """The proactive re-admission op for this step, or [] when not triggered.

    `archive` is the per-session ArchiveView (Features.archive). Returns a
    one-op plan only when a missing reference is actually grounded in the
    archive; the semantic_retrieval operator then performs the search and
    ingestion under the normal guardrail + trace path.
    """
    if archive is None or len(archive) == 0:
        return []
    query_span = latest_query_span(window)
    if query_span is None:
        return []
    missing = missing_evidence(window, query_span)
    if not missing:
        return []
    # Grounding gate: some archived span must lexically match the missing
    # tokens themselves (not merely the full query text, whose template
    # words could overlap archived boilerplate). When the missing set has
    # numbers, a hit must carry one of them - word-only overlap on template
    # vocabulary is not evidence (module docstring, gate 2).
    missing_digits = {t for t in missing if t.isdigit()}
    probe_query = " ".join(sorted(missing))
    hits = archive.search(probe_query, top_k=3, min_score=min_score)
    if not hits:
        return []
    if missing_digits and not any(missing_digits & tokenize(h.content) for h in hits):
        return []
    return [
        PlannedOp(
            op="semantic_retrieval",
            params={
                "query": query_span.content,
                "top_k": top_k,
                "min_score": min_score,
            },
            order=0,
        )
    ]
