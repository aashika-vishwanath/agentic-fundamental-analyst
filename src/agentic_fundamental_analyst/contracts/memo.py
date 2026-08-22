"""Contracts for Phase 5 — the Synthesizer (draft + resolve) and Red-Team, and
the `Memo` PRD §3 actually promises. See .agents/plans/phase-5-synthesis-redteam-pipeline.md
for the full design rationale, including two deliberate deviations from PRD §3's
illustrative sketch: `MemoSection.title` is a closed Literal (not `str`), and
`Memo.coverage_gaps` is `list[CoverageGap]` (not the sketch's bare `list[str]`),
both for consistency with every other closed-set/coverage-gap convention already
in this codebase.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.investigation import InvestigationVerdict
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote


class Rating(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class ConvictionTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# PRD §3's ten sections, in the fixed order §3's table specifies. Closed Literal
# so every downstream stage (grounding gate, red-team's `section` field, the
# structural "all ten present, in order" check) can address a section by a
# stable key instead of free text -- same closed-set idiom as FilingSection /
# FinancialFlagMetric elsewhere in this codebase.
MemoSectionTitle = Literal[
    "executive_summary_and_recommendation",
    "investment_thesis",
    "business_overview",
    "financial_analysis",
    "earnings_quality_and_red_flags",
    "valuation",
    "catalysts",
    "risks_and_mitigants",
    "recommendation_and_sizing",
    "appendix_and_sourcing",
]

MEMO_SECTION_ORDER: tuple[MemoSectionTitle, ...] = (
    "executive_summary_and_recommendation",
    "investment_thesis",
    "business_overview",
    "financial_analysis",
    "earnings_quality_and_red_flags",
    "valuation",
    "catalysts",
    "risks_and_mitigants",
    "recommendation_and_sizing",
    "appendix_and_sourcing",
)

# PRD §3's real display names, for anything that renders a title to a human
# (render.py). Deliberately not derived from the Literal's snake_case value
# (e.g. "Recommendation & Sizing" and "Appendix / Sourcing" don't round-trip
# from `.replace("_", " ").title()`).
MEMO_SECTION_DISPLAY_NAMES: dict[MemoSectionTitle, str] = {
    "executive_summary_and_recommendation": "Executive Summary & Recommendation",
    "investment_thesis": "Investment Thesis",
    "business_overview": "Business Overview",
    "financial_analysis": "Financial Analysis",
    "earnings_quality_and_red_flags": "Earnings Quality & Red Flags",
    "valuation": "Valuation",
    "catalysts": "Catalysts",
    "risks_and_mitigants": "Risks & Mitigants",
    "recommendation_and_sizing": "Recommendation & Sizing",
    "appendix_and_sourcing": "Appendix / Sourcing",
}


class MemoSectionAgentOutput(BaseModel):
    """Shared by the draft and resolve passes' own output_type. Unlike
    Phase 4's agents (which never trusted the model with metadata a stage
    function always rebuilds), `cited_figures` IS asked of the model here --
    Section 10 (Appendix/Sourcing)'s "literal traceability table" only exists
    if the model states what it's citing. The per-section grounding gate
    (agents/memo_grounding.py) then verifies both `content`'s numbers AND
    `cited_figures`' values against real upstream data -- never trusts either
    in isolation."""

    title: MemoSectionTitle
    content: str
    cited_figures: list[SourcedFigure]
    cited_quotes: list[SourcedQuote] = []


class MemoSection(BaseModel):
    """Post-grounding-gate -- identical shape to MemoSectionAgentOutput, kept
    as a separate type for the same reason FinancialAnalystOutput is separate
    from FinancialAnalystAgentOutput: this is what a pipeline stage actually
    returns, after code-owned handling (here: the per-section fallback)."""

    title: MemoSectionTitle
    content: str
    cited_figures: list[SourcedFigure]
    cited_quotes: list[SourcedQuote] = []


class SynthesizerDraftAgentOutput(BaseModel):
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSectionAgentOutput]


class MemoDraft(BaseModel):
    ticker: str
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSection]
    coverage_gaps: list[CoverageGap]


class AttackCategory(str, Enum):
    UNTRACEABLE_CLAIM = "untraceable_claim"
    BOILERPLATE = "boilerplate"


class AttackCandidate(BaseModel):
    """Agent-authored, unverified -- quoted_claim is NOT trusted until
    _resolve_attacks() verifies it's a real substring of the section it
    names, same 'candidate' idiom as FlagCandidate / EvidenceCandidate."""

    section: MemoSectionTitle
    category: AttackCategory
    quoted_claim: str
    critique: str
    checklist_item: str | None = None


class RedTeamAgentOutput(BaseModel):
    attack_candidates: list[AttackCandidate]


class Attack(BaseModel):
    """Post quote-verification -- quoted_claim is confirmed to be a real
    (whitespace-normalized) substring of the named section's content."""

    section: MemoSectionTitle
    category: AttackCategory
    quoted_claim: str
    critique: str
    checklist_item: str | None = None


class RedTeamAttack(BaseModel):
    attacks: list[Attack]
    dropped_candidates: list[str]  # diagnostic only -- never delivered in the memo


class ResolutionPath(str, Enum):
    RE_GROUNDED = "re_grounded"
    DOWNGRADED = "downgraded"
    CUT = "cut"


class AttackResolution(BaseModel):
    attack_index: int  # 0-based position into RedTeamAttack.attacks -- closed-set-by-index idiom
    resolution: ResolutionPath
    explanation: str
    model_addressed: bool = True  # False only for a code-synthesized structural fallback


class SynthesizerResolveAgentOutput(BaseModel):
    resolutions: list[AttackResolution]
    rating: Rating
    conviction: ConvictionTier
    sections: list[MemoSectionAgentOutput]


class Memo(BaseModel):
    ticker: str
    rating: Rating
    conviction: ConvictionTier
    generated_at: datetime
    sections: list[MemoSection]
    coverage_gaps: list[CoverageGap]
    investigations: list[InvestigationVerdict]
    resolutions: list[AttackResolution]
