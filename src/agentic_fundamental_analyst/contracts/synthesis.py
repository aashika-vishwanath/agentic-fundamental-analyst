"""Typed inter-stage boundaries for Phase 5's three synthesis agents. Kept
separate from contracts/memo.py since these are plumbing wrappers (never part
of the delivered Memo), not the memo's own shape.
"""

from datetime import date

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import CoverageGap, FinancialStatementBundle
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.investigation import InvestigationVerdict
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.memo import MemoDraft, RedTeamAttack
from agentic_fundamental_analyst.contracts.ratios import RatioTrendBundle
from agentic_fundamental_analyst.contracts.valuation import ValuationResult


class MemoSynthesisInput(BaseModel):
    """The one typed bundle the draft pass (and, wrapped further below, the
    red-team/resolve passes) consume. Field order matters: stable, long-lived
    content first (filing text, financials) per CLAUDE.md's prompt-caching
    convention -- narrated/derived content (flags, investigations, the three
    Phase 4 summaries) last. Carries SUMMARY STRINGS (not the full
    FinancialAnalystOutput/FilingsAnalystOutput/TranscriptAnalystOutput
    objects) for the three Stage-2 analysts, to avoid duplicating their
    `flags` -- the canonical post-consolidation flag list is
    `consolidated_flags` below."""

    ticker: str
    intake: TickerIntakeResult
    filings: FilingSections
    ratio_trend: RatioTrendBundle
    financials: FinancialStatementBundle
    latest_price: float
    latest_price_date: date
    macro_bundles: list[MacroSeriesBundle]
    valuation_result: ValuationResult
    financial_analyst_summary: str
    filings_analyst_summary: str
    transcript_analyst_summary: str | None
    sector_summary: str
    macro_summary: str
    valuation_summary: str
    consolidated_flags: list[ConsolidatedFlag]
    investigations: list[InvestigationVerdict]
    coverage_gaps: list[CoverageGap]


class RedTeamInput(BaseModel):
    draft: MemoDraft
    synthesis_input: MemoSynthesisInput


class SynthesizerResolveInput(BaseModel):
    draft: MemoDraft
    red_team: RedTeamAttack
    synthesis_input: MemoSynthesisInput
