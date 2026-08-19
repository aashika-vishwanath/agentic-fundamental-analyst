"""Verbatim quote grounding — shared by the Filings and Transcript Analysts
(Phase 2). Prose input has no closed, enumerable table to index into the way
Phase 1's RatioTrendBundle does, so grounding here means: the agent's claim
must carry the exact source-text span it's drawn from, and this module
verifies that span really appears in the source, before any candidate is
promoted to a real Flag. See the Phase 2 plan's Problem/Solution for why."""

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def quote_is_grounded(quote: str, source_text: str | None) -> bool:
    """True iff `quote` is a real (whitespace-normalized) substring of
    `source_text`. Normalization tolerates the HTML parser's own whitespace
    irregularities without being lenient about actual content differences —
    a paraphrased "quote" is dropped, not fuzzy-matched."""
    if source_text is None:
        return False
    return normalize_whitespace(quote) in normalize_whitespace(source_text)
