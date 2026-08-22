"""Eval dataset for the Synthesizer resolve pass (Phase 5).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.synthesizer_resolve
Passing bar (see .agents/plans/phase-5-synthesis-redteam-pipeline.md):
- AllAttacksAddressedEvaluator at 100% (holds by construction — run_synthesizer_resolve's
  _fill_missing_resolutions guarantees it) — `model_addressed_fraction` is the real signal
  (how many resolutions came from the model itself vs. the structural fallback).
- MemoGroundingEvaluator's `is_grounded` at 100% and AllTenSectionsPresentInOrder at 100%.
- ExpectedResolutionPath (recall) passes on at least 3/4 cases (softest bar for the one truly
  judgment-laden check here — a model choosing re_grounded over downgraded for a borderline
  claim is a reasonable disagreement, not necessarily a defect; never loosen further without
  flagging it).
- LLMJudge rubric (resolution reads as survived, not ignored — memo-writing skill §4 Pass 3
  verbatim) passes on at least 3/4.
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.memo_grounding import (
    known_numbers_from_synthesis_input,
    section_is_grounded,
)
from agentic_fundamental_analyst.agents.models import SYNTHESIZER_RESOLVE_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import expand_known_numbers
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
    Attack,
    AttackCategory,
    Memo,
    MemoDraft,
    MemoSection,
    RedTeamAttack,
)
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.contracts.synthesis import (
    MemoSynthesisInput,
    SynthesizerResolveInput,
)
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
        "Approximately 30% of fiscal 2024 revenue came from our five largest automotive customers."
    ),
    item_7_mdna=(
        "Net revenue grew 15% year over year to $552 million. Capital expenditures increased "
        "to $95 million from $38 million in the prior year, reflecting construction costs for "
        "our new Ohio assembly facility, which management expects to reach full utilization "
        "in fiscal 2026."
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

_GOOD_CONTENT: dict[str, str] = {
    "executive_summary_and_recommendation": (
        "HOLD, medium conviction: MRBT grew revenue 15% to $552 million in FY2024 while "
        "ramping capex for a new Ohio facility."
    ),
    "investment_thesis": (
        "MRBT's FY2024 capex ramp to $95 million funds a new Ohio facility; if utilization "
        "falls short there, this pillar breaks."
    ),
    "business_overview": (
        "MRBT designs robotic arms and vision-guided assembly systems for automotive and "
        "electronics manufacturers."
    ),
    "financial_analysis": (
        "Revenue grew from $480 million in FY2023 to $552 million in FY2024, a 15% increase."
    ),
    "earnings_quality_and_red_flags": (
        "Capex/D&A rose to 2.79x in FY2024, driven by the disclosed Ohio facility buildout."
    ),
    "valuation": "No trailing DCF or peer comps are available for this ticker at this time.",
    # This section deliberately overstates a disclosed expectation as a hard fact --
    # the target of the downgrade-case attack below.
    "catalysts": (
        "The Ohio facility will definitely reach full production capacity by the second "
        "quarter of fiscal 2026."
    ),
    "risks_and_mitigants": (
        "Approximately 30% of FY2024 revenue came from MRBT's five largest automotive customers."
    ),
    # This section deliberately implies a consensus/Street comparison that does not
    # exist in this system -- the target of the cut-case attack below.
    "recommendation_and_sizing": (
        "HOLD with medium conviction; shares trade below the average Street price target."
    ),
    "appendix_and_sourcing": "See the sourcing table for every figure cited above.",
}


def _sections() -> list[MemoSection]:
    return [
        MemoSection(title=title, content=_GOOD_CONTENT[title], cited_figures=[])  # type: ignore[arg-type]
        for title in MEMO_SECTION_ORDER
    ]


_DRAFT = MemoDraft(
    ticker="MRBT",
    rating="hold",  # type: ignore[arg-type]
    conviction="medium",  # type: ignore[arg-type]
    sections=_sections(),
    coverage_gaps=[],
)

_REGROUND_ATTACK = Attack(
    section="financial_analysis",  # type: ignore[arg-type]
    category=AttackCategory.UNTRACEABLE_CLAIM,
    quoted_claim=(
        "Revenue grew from $480 million in FY2023 to $552 million in FY2024, a 15% increase."
    ),
    critique="No SourcedFigure is cited for either revenue figure in this section.",
)
_DOWNGRADE_ATTACK = Attack(
    section="catalysts",  # type: ignore[arg-type]
    category=AttackCategory.UNTRACEABLE_CLAIM,
    quoted_claim=(
        "The Ohio facility will definitely reach full production capacity by the second "
        "quarter of fiscal 2026."
    ),
    critique=(
        "MD&A states this as management's expectation, not a certainty -- 'will definitely' "
        "overstates a disclosed forward-looking expectation as established fact."
    ),
)
_CUT_ATTACK = Attack(
    section="recommendation_and_sizing",  # type: ignore[arg-type]
    category=AttackCategory.UNTRACEABLE_CLAIM,
    quoted_claim="shares trade below the average Street price target.",
    critique=(
        "This system has no consensus/analyst-estimate data source -- there is no 'Street "
        "price target' anywhere in synthesis_input. This claim has no basis and should be cut."
    ),
)


@dataclass
class MemoGroundingEvaluator(Evaluator[SynthesizerResolveInput, Memo, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[SynthesizerResolveInput, Memo, dict]
    ) -> dict[str, bool]:
        known = expand_known_numbers(known_numbers_from_synthesis_input(ctx.inputs.synthesis_input))
        all_grounded = all(section_is_grounded(s, known) for s in ctx.output.sections)  # type: ignore[arg-type]
        fallback_triggered = any(
            g.reason == "numeric_grounding_check_failed" for g in ctx.output.coverage_gaps
        )
        return {"is_grounded": all_grounded, "fallback_triggered": fallback_triggered}


@dataclass
class AllTenSectionsPresentInOrder(Evaluator[SynthesizerResolveInput, Memo, dict]):
    def evaluate(self, ctx: EvaluatorContext[SynthesizerResolveInput, Memo, dict]) -> bool:
        return [s.title for s in ctx.output.sections] == list(MEMO_SECTION_ORDER)


@dataclass
class AllAttacksAddressedEvaluator(Evaluator[SynthesizerResolveInput, Memo, dict]):
    """Hard gate: every attack index has exactly one resolution record."""

    def evaluate(
        self, ctx: EvaluatorContext[SynthesizerResolveInput, Memo, dict]
    ) -> dict[str, float | bool]:
        n_attacks = len(ctx.inputs.red_team.attacks)
        indices = sorted(r.attack_index for r in ctx.output.resolutions)
        all_addressed = indices == list(range(n_attacks))
        model_addressed_fraction = (
            sum(1 for r in ctx.output.resolutions if r.model_addressed) / n_attacks
            if n_attacks
            else 1.0
        )
        return {
            "all_attacks_addressed": all_addressed,
            "model_addressed_fraction": model_addressed_fraction,
        }


@dataclass
class ExpectedResolutionPath(Evaluator[SynthesizerResolveInput, Memo, dict]):
    def evaluate(self, ctx: EvaluatorContext[SynthesizerResolveInput, Memo, dict]) -> bool:
        expected: dict[int, str] | None = (ctx.metadata or {}).get(
            "expected_resolution_path_by_index"
        )
        if not expected:
            return True
        by_index = {r.attack_index: r.resolution.value for r in ctx.output.resolutions}
        return all(by_index.get(i) == path for i, path in expected.items())


_RESOLUTION_QUALITY_RUBRIC = (
    "For every attack, the corresponding section of the rewritten memo reads as if it already "
    "survived that attack, not as if the attack was ignored: a re_grounded resolution keeps "
    "the claim but now backs it with a real cited figure; a downgraded resolution rewrites the "
    "claim as an explicitly stated assumption or expectation rather than a certainty; a cut "
    "resolution removes the challenged claim from the rewritten section entirely rather than "
    "leaving it in unchanged."
)

_REGROUND_META: dict[str, object] = {"expected_resolution_path_by_index": {0: "re_grounded"}}
_DOWNGRADE_META: dict[str, object] = {"expected_resolution_path_by_index": {0: "downgraded"}}
_CUT_META: dict[str, object] = {"expected_resolution_path_by_index": {0: "cut"}}
_MULTI_META: dict[str, object] = {
    "expected_resolution_path_by_index": {0: "re_grounded", 1: "downgraded", 2: "cut"}
}

dataset = Dataset(
    name="synthesizer_resolve",
    cases=[
        Case(
            name="attack_reground_with_real_source_available",
            inputs=SynthesizerResolveInput(
                draft=_DRAFT,
                red_team=RedTeamAttack(attacks=[_REGROUND_ATTACK], dropped_candidates=[]),
                synthesis_input=_SYNTHESIS_INPUT,
            ),
            metadata=_REGROUND_META,
        ),
        Case(
            name="attack_downgrade_forward_looking_no_hard_source",
            inputs=SynthesizerResolveInput(
                draft=_DRAFT,
                red_team=RedTeamAttack(attacks=[_DOWNGRADE_ATTACK], dropped_candidates=[]),
                synthesis_input=_SYNTHESIS_INPUT,
            ),
            metadata=_DOWNGRADE_META,
        ),
        Case(
            name="attack_cut_irrelevant_claim",
            inputs=SynthesizerResolveInput(
                draft=_DRAFT,
                red_team=RedTeamAttack(attacks=[_CUT_ATTACK], dropped_candidates=[]),
                synthesis_input=_SYNTHESIS_INPUT,
            ),
            metadata=_CUT_META,
        ),
        Case(
            name="multiple_attacks_all_addressed",
            inputs=SynthesizerResolveInput(
                draft=_DRAFT,
                red_team=RedTeamAttack(
                    attacks=[_REGROUND_ATTACK, _DOWNGRADE_ATTACK, _CUT_ATTACK],
                    dropped_candidates=[],
                ),
                synthesis_input=_SYNTHESIS_INPUT,
            ),
            metadata=_MULTI_META,
        ),
    ],
    evaluators=[
        AllAttacksAddressedEvaluator(),
        MemoGroundingEvaluator(),
        AllTenSectionsPresentInOrder(),
        ExpectedResolutionPath(),
        LLMJudge(rubric=_RESOLUTION_QUALITY_RUBRIC, model=SYNTHESIZER_RESOLVE_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.synthesizer_resolve import run_synthesizer_resolve

    report = dataset.evaluate_sync(run_synthesizer_resolve)
    report.print(include_input=False, include_output=True, include_durations=True)
