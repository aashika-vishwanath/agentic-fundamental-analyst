"""Eval dataset for Red-Team (Phase 5).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.red_team
Passing bar (see .agents/plans/phase-5-synthesis-redteam-pipeline.md):
- AttackQuoteGroundedEvaluator at 100% (holds by construction — run_red_team drops any
  fabricated quoted_claim before it reaches the output).
- ExpectedAttackCategoryRaised passes on the three flawed-draft cases.
- FewAttacksOnCleanDraft passes on the clean case (the over-attacking guard).
- LLMJudge substantiveness rubric passes on at least 3/4 (softest bar — never loosen the
  rubric to make a failure disappear, flag it instead).
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.grounding import quote_is_grounded
from agentic_fundamental_analyst.agents.models import RED_TEAM_MODEL
from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import (
    CoverageGap,
    FinancialStatementBundle,
    FiscalPeriod,
)
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import (
    MEMO_SECTION_ORDER,
    MemoDraft,
    MemoSection,
    RedTeamAttack,
)
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.contracts.synthesis import MemoSynthesisInput, RedTeamInput
from agentic_fundamental_analyst.contracts.valuation import ValuationAssumptions, ValuationResult
from agentic_fundamental_analyst.ratios import compute_trend_bundle

_PERIOD_2023 = FiscalPeriod(
    fiscal_year=2023,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2023, 12, 31),
    revenue=480_000_000.0,
    net_income=52_000_000.0,
    capex=38_000_000.0,
    depreciation_amortization=30_000_000.0,
    accounts_receivable=55_000_000.0,
    inventory=60_000_000.0,
    total_assets=900_000_000.0,
    operating_cash_flow=88_000_000.0,
    cost_of_revenue=300_000_000.0,
    sga_expense=70_000_000.0,
    current_assets=250_000_000.0,
    ppe_gross=400_000_000.0,
    total_debt=150_000_000.0,
)
_PERIOD_2024 = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2024, 12, 31),
    revenue=552_000_000.0,
    net_income=66_000_000.0,
    capex=95_000_000.0,
    depreciation_amortization=34_000_000.0,
    accounts_receivable=63_000_000.0,
    inventory=68_000_000.0,
    total_assets=1_020_000_000.0,
    operating_cash_flow=101_000_000.0,
    cost_of_revenue=336_000_000.0,
    sga_expense=79_000_000.0,
    current_assets=280_000_000.0,
    ppe_gross=470_000_000.0,
    total_debt=180_000_000.0,
)
_FINANCIALS = FinancialStatementBundle(
    ticker="MRBT", cik="0001234567", periods=[_PERIOD_2023, _PERIOD_2024], coverage_gaps=[]
)
_INTAKE = TickerIntakeResult(
    ticker="MRBT",
    cik="0001234567",
    sic_code="3559",
    sic_description="Special Industry Machinery",
    in_scope=True,
    exclusion_reason=None,
)
_FILINGS = FilingSections(
    accession_number="0001234567-25-000012",
    filed_date=date(2025, 2, 18),
    period_of_report=date(2024, 12, 31),
    item_1_business=(
        "Meridian Robotics Inc. designs and manufactures robotic arms and vision-guided "
        "assembly systems for automotive and electronics manufacturers."
    ),
    item_1a_risk_factors=(
        "We face intense competition and are subject to general economic, political, and "
        "regulatory risks that could adversely affect our business, financial condition, and "
        "results of operations. Approximately 30% of fiscal 2024 revenue came from our five "
        "largest automotive customers, and a pullback in automotive capital spending could "
        "reduce demand for MeridianArm systems."
    ),
    item_7_mdna=(
        "Net revenue grew 15% year over year to $552 million. Capital expenditures increased "
        "to $95 million from $38 million in the prior year, reflecting construction costs for "
        "our new Ohio assembly facility, which management expects to add approximately $120 "
        "million of annual production capacity once fully ramped in fiscal 2026."
    ),
    item_9a_controls="Disclosure controls and procedures were effective as of the period end.",
    eightk_item_bodies={},
    eightk_item_sources={},
    coverage_gaps=[],
)
_MACRO_BUNDLES = [
    MacroSeriesBundle(
        series_id="DGS10", points=[MacroSeriesPoint(obs_date=date(2025, 2, 14), value=4.2)]
    )
]
_ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2025, 2, 14),
    equity_risk_premium=0.055,
    discount_rate=0.097,
    terminal_growth=0.025,
)
_VALUATION_RESULT = ValuationResult(
    ticker="MRBT", assumptions=_ASSUMPTIONS, dcf=None, comps=None, coverage_gaps=[]
)
_CAPEX_FLAG = Flag(
    metric="capex_to_depreciation_ratio",
    fiscal_year=2024,
    fiscal_period="FY",
    severity=Severity.HIGH,
    description="Capex/D&A jumped to 2.79x in FY2024, driven by the new Ohio assembly facility.",
    source=SourcedFigure(
        value=2.79,
        source="ratios.capex_to_depreciation_ratio:MRBT:2024FY",
        as_of=date(2024, 12, 31),
    ),
)
_CONSOLIDATED_CAPEX = ConsolidatedFlag(
    flags=[_CAPEX_FLAG],
    summary="Capex/D&A escalated in FY2024 alongside the Ohio facility buildout.",
)

_SYNTHESIS_INPUT = MemoSynthesisInput(
    ticker="MRBT",
    intake=_INTAKE,
    filings=_FILINGS,
    ratio_trend=compute_trend_bundle(_FINANCIALS),
    financials=_FINANCIALS,
    latest_price=54.0,
    latest_price_date=date(2025, 2, 14),
    macro_bundles=_MACRO_BUNDLES,
    valuation_result=_VALUATION_RESULT,
    financial_analyst_summary="Revenue and net income both grew double digits in FY2024.",
    filings_analyst_summary="MD&A discloses the Ohio facility buildout as the capex driver.",
    transcript_analyst_summary=None,
    sector_summary="MRBT trades in line with industrial-automation peers.",
    macro_summary="Rates have been stable near 4.2%.",
    valuation_summary="No DCF or comps are available for this ticker at this time.",
    consolidated_flags=[_CONSOLIDATED_CAPEX],
    investigations=[],
    coverage_gaps=[
        CoverageGap(field="transcript", reason="no 8-K transcript exhibit found"),
        CoverageGap(field="peers", reason="insufficient peer data for SIC 3559"),
    ],
)

_GENERIC_CONTENT = "Well positioned to benefit from industry tailwinds in a growing market."
_GOOD_CONTENT: dict[str, str] = {
    "executive_summary_and_recommendation": (
        "HOLD, medium conviction: MRBT grew revenue 15% to $552 million in FY2024 while "
        "ramping capex for a new Ohio facility expected to add $120 million of annual capacity."
    ),
    "investment_thesis": (
        "MRBT's FY2024 capex ramp to $95 million (from $38 million) funds a new Ohio facility "
        "management expects to complete in fiscal 2026; if utilization there falls short of "
        "the disclosed 30% automotive-customer exposure, this pillar breaks."
    ),
    "business_overview": (
        "MRBT designs robotic arms and vision-guided assembly systems for automotive and "
        "electronics manufacturers under the MeridianArm and VisionLock lines."
    ),
    "financial_analysis": (
        "Revenue grew from $480 million in FY2023 to $552 million in FY2024, a 15% increase, "
        "while capex rose from $38 million to $95 million over the same period."
    ),
    "earnings_quality_and_red_flags": (
        "Capex/D&A rose to 2.79x in FY2024, driven by the disclosed Ohio facility buildout -- "
        "a real red flag under this system's checklist, investigated and reported here rather "
        "than omitted."
    ),
    "valuation": "No trailing DCF or peer comps are available for this ticker at this time.",
    "catalysts": "The Ohio facility is expected to reach full production capacity in fiscal 2026.",
    "risks_and_mitigants": (
        "Approximately 30% of FY2024 revenue came from MRBT's five largest automotive "
        "customers; a pullback in automotive capital spending would concentrate downside risk."
    ),
    "recommendation_and_sizing": (
        "HOLD with medium conviction, tied to the Ohio facility ramp thesis pillar; no dollar "
        "or percent-of-portfolio position size is provided."
    ),
    "appendix_and_sourcing": "See the sourcing table for every figure cited above.",
}


def _base_sections(overrides: dict[str, str] | None = None) -> list[MemoSection]:
    overrides = overrides or {}
    return [
        MemoSection(
            title=title,  # type: ignore[arg-type]
            content=overrides.get(title, _GOOD_CONTENT[title]),
            cited_figures=[],
        )
        for title in MEMO_SECTION_ORDER
    ]


def _draft(overrides: dict[str, str] | None = None) -> MemoDraft:
    return MemoDraft(
        ticker="MRBT",
        rating="hold",  # type: ignore[arg-type]
        conviction="medium",  # type: ignore[arg-type]
        sections=_base_sections(overrides),
        coverage_gaps=[],
    )


_BOILERPLATE_THESIS_DRAFT = _draft({"investment_thesis": _GENERIC_CONTENT})
_MISSING_CHECKLIST_DRAFT = _draft(
    {
        "earnings_quality_and_red_flags": (
            "No material earnings-quality concerns were identified this period."
        )
    }
)
_GENERIC_RISK_DRAFT = _draft(
    {
        "risks_and_mitigants": (
            "We face intense competition and are subject to general economic, political, and "
            "regulatory risks that could adversely affect our business, financial condition, "
            "and results of operations."
        )
    }
)
_CLEAN_DRAFT = _draft()


@dataclass
class AttackQuoteGroundedEvaluator(Evaluator[RedTeamInput, RedTeamAttack, dict]):
    """Hard gate: every surviving Attack.quoted_claim really is a verbatim
    substring of the draft section it names -- independently re-derived, not
    just trusting run_red_team applied _resolve_attacks correctly."""

    def evaluate(self, ctx: EvaluatorContext[RedTeamInput, RedTeamAttack, dict]) -> bool:
        content_by_section = {s.title: s.content for s in ctx.inputs.draft.sections}
        return all(
            quote_is_grounded(a.quoted_claim, content_by_section.get(a.section))
            for a in ctx.output.attacks
        )


@dataclass
class ExpectedAttackCategoryRaised(Evaluator[RedTeamInput, RedTeamAttack, dict]):
    def evaluate(self, ctx: EvaluatorContext[RedTeamInput, RedTeamAttack, dict]) -> bool:
        expected_category = (ctx.metadata or {}).get("expected_category")
        expected_section = (ctx.metadata or {}).get("expected_section")
        if expected_category is None:
            return True
        return any(
            a.category.value == expected_category and a.section == expected_section
            for a in ctx.output.attacks
        )


@dataclass
class FewAttacksOnCleanDraft(Evaluator[RedTeamInput, RedTeamAttack, dict]):
    def evaluate(self, ctx: EvaluatorContext[RedTeamInput, RedTeamAttack, dict]) -> bool:
        if not (ctx.metadata or {}).get("expect_few_attacks"):
            return True
        return len(ctx.output.attacks) <= 1


_SUBSTANTIVENESS_RUBRIC = (
    "Each attack cites the specific section and quotes the specific offending sentence "
    "(quoted_claim), and the critique explains concretely what's wrong -- not a vague "
    "'this could be more specific.' A boilerplate attack on earnings_quality_and_red_flags "
    "names the specific checklist item skipped when one is skipped. The red-team does not "
    "attack a disclosed assumption (e.g. a discount rate framed as an assumption) merely for "
    "being an assumption."
)

# Explicit dict[str, object] annotations so every Case's metadata type param
# unifies into one list -- Case's MetadataT is invariant, and pyright would
# otherwise infer a distinct concrete dict[str, str] / dict[str, bool] per
# call site, which cannot share a list.
_BOILERPLATE_THESIS_METADATA: dict[str, object] = {
    "expected_category": "boilerplate",
    "expected_section": "investment_thesis",
}
_MISSING_CHECKLIST_METADATA: dict[str, object] = {
    "expected_category": "boilerplate",
    "expected_section": "earnings_quality_and_red_flags",
}
_GENERIC_RISK_METADATA: dict[str, object] = {
    "expected_category": "boilerplate",
    "expected_section": "risks_and_mitigants",
}
_FEW_ATTACKS_METADATA: dict[str, object] = {"expect_few_attacks": True}

dataset = Dataset(
    name="red_team",
    cases=[
        Case(
            name="boilerplate_thesis_no_falsifiable_trigger",
            inputs=RedTeamInput(draft=_BOILERPLATE_THESIS_DRAFT, synthesis_input=_SYNTHESIS_INPUT),
            metadata=_BOILERPLATE_THESIS_METADATA,
        ),
        Case(
            name="missing_checklist_item_in_earnings_quality",
            inputs=RedTeamInput(draft=_MISSING_CHECKLIST_DRAFT, synthesis_input=_SYNTHESIS_INPUT),
            metadata=_MISSING_CHECKLIST_METADATA,
        ),
        Case(
            name="generic_risk_factor_copy_paste",
            inputs=RedTeamInput(draft=_GENERIC_RISK_DRAFT, synthesis_input=_SYNTHESIS_INPUT),
            metadata=_GENERIC_RISK_METADATA,
        ),
        Case(
            name="clean_draft_few_or_no_attacks",
            inputs=RedTeamInput(draft=_CLEAN_DRAFT, synthesis_input=_SYNTHESIS_INPUT),
            metadata=_FEW_ATTACKS_METADATA,
        ),
    ],
    evaluators=[
        AttackQuoteGroundedEvaluator(),
        ExpectedAttackCategoryRaised(),
        FewAttacksOnCleanDraft(),
        LLMJudge(rubric=_SUBSTANTIVENESS_RUBRIC, model=RED_TEAM_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.red_team import run_red_team

    report = dataset.evaluate_sync(run_red_team)
    report.print(include_input=False, include_output=True, include_durations=True)
