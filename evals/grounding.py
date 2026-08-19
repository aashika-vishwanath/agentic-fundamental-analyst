"""Shared grounding-check logic for the Filings and Transcript Analyst eval
datasets (Phase 2). Each dataset's own Evaluator class stays concrete (same
shape as evals/financial_statements.py's FinancialStatementsGroundingEvaluator)
because "how do I find the source text a given flag should be grounded
against" genuinely differs per agent (Filings routes by section + 8-K item
number; Transcript has exactly one source text) — only the actual substring
check is shared, via agents/grounding.py::quote_is_grounded.
"""

from collections.abc import Callable

from agentic_fundamental_analyst.agents.grounding import quote_is_grounded
from agentic_fundamental_analyst.contracts.flags import Flag
from agentic_fundamental_analyst.contracts.sourcing import SourcedQuote


def flags_are_quote_grounded(
    flags: list[Flag], source_text_for: Callable[[Flag], str | None]
) -> bool:
    """True iff every flag's source is a SourcedQuote whose .text verifies
    as a real substring of whatever source_text_for resolves for it."""
    for flag in flags:
        if not isinstance(flag.source, SourcedQuote):
            return False
        if not quote_is_grounded(flag.source.text, source_text_for(flag)):
            return False
    return True
