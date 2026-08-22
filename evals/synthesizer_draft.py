"""Eval dataset for the Synthesizer draft pass (Phase 5).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.synthesizer_draft
Passing bar (see .agents/plans/phase-5-synthesis-redteam-pipeline.md):
- MemoGroundingEvaluator's `is_grounded` at 100% (holds by construction — the runtime gate
  guarantees it) and `fallback_triggered` at 0% across cases — the real quality signal.
- AllTenSectionsPresentInOrder at 100% — hard gate.
- ExpectedCoverageGapPropagated passes on the thin-data case.
- LLMJudge rubric (good-vs-boilerplate per the memo-writing skill, no DEFERRED content, the
  reframed thesis rule) passes on at least 2/3 (softest bar — never loosen the rubric to make
  a failure disappear, flag it instead).
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.memo_grounding import (
    known_numbers_from_synthesis_input,
    section_is_grounded,
)
from agentic_fundamental_analyst.agents.models import SYNTHESIZER_DRAFT_MODEL
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
from agentic_fundamental_analyst.contracts.investigation import (
    EvidenceItem,
    EvidenceStance,
    InvestigationTrajectory,
    InvestigationVerdict,
    VerdictType,
)
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import MEMO_SECTION_ORDER, MemoDraft
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.contracts.synthesis import MemoSynthesisInput
from agentic_fundamental_analyst.contracts.valuation import (
    DCFResult,
    DCFScenario,
    PeerCompsResult,
    PeerMultiples,
    ValuationAssumptions,
    ValuationResult,
)
from agentic_fundamental_analyst.ratios import compute_trend_bundle

# --- fictional company: Meridian Robotics Inc. (MRBT), industrial automation ---

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
    capex=95_000_000.0,  # ramp for a new robotics assembly facility, disclosed in item_7_mdna
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
_RATIO_TREND = compute_trend_bundle(_FINANCIALS)

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
        "assembly systems for automotive and electronics manufacturers, sold under the "
        "MeridianArm and VisionLock product lines through a direct sales force serving "
        "roughly 340 industrial customers across North America and Europe."
    ),
    item_1a_risk_factors=(
        "Approximately 30% of fiscal 2024 revenue came from our five largest automotive "
        "customers, and a pullback in automotive capital spending could reduce demand for "
        "MeridianArm systems. Our new assembly facility in Ohio, which began production in "
        "the fourth quarter of fiscal 2024, has not yet operated at full utilization, and a "
        "delay in ramping output could pressure near-term gross margin."
    ),
    item_7_mdna=(
        "Net revenue grew 15% year over year to $552 million, driven by expanded orders for "
        "the VisionLock product line among electronics manufacturers. Capital expenditures "
        "increased to $95 million from $38 million in the prior year, reflecting construction "
        "and equipment costs for our new Ohio assembly facility, which management expects to "
        "add approximately $120 million of annual production capacity once fully ramped in "
        "fiscal 2026. Gross margin was 39.1%, up from 37.5% in the prior year."
    ),
    item_9a_controls=(
        "Based on this evaluation, our Chief Executive Officer and Chief Financial Officer "
        "concluded that our disclosure controls and procedures were effective as of the "
        "period end."
    ),
    eightk_item_bodies={},
    eightk_item_sources={},
    coverage_gaps=[],
)

_MACRO_BUNDLES = [
    MacroSeriesBundle(
        series_id="DGS10", points=[MacroSeriesPoint(obs_date=date(2025, 2, 14), value=4.2)]
    ),
    MacroSeriesBundle(
        series_id="FEDFUNDS", points=[MacroSeriesPoint(obs_date=date(2025, 2, 14), value=4.5)]
    ),
    MacroSeriesBundle(
        series_id="T10Y2Y", points=[MacroSeriesPoint(obs_date=date(2025, 2, 14), value=0.3)]
    ),
]

_ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2025, 2, 14),
    equity_risk_premium=0.055,
    discount_rate=0.097,
    terminal_growth=0.025,
)
_DCF = DCFResult(
    cash_flows=[50_000_000.0, 63_000_000.0, 6_000_000.0],
    scenarios=[
        DCFScenario(
            label="bull", discount_rate=0.087, terminal_growth=0.03, present_value=612_000_000.0
        ),
        DCFScenario(
            label="base", discount_rate=0.097, terminal_growth=0.025, present_value=540_000_000.0
        ),
        DCFScenario(
            label="bear", discount_rate=0.107, terminal_growth=0.02, present_value=478_000_000.0
        ),
    ],
)
_TARGET_MULT = PeerMultiples(ticker="MRBT", pe_ratio=19.5, ev_to_revenue=2.4, ev_to_ebitda=11.2)
_PEER_MULT = PeerMultiples(ticker="AUTM", pe_ratio=22.0, ev_to_revenue=2.8, ev_to_ebitda=12.5)
_COMPS = PeerCompsResult(
    target=_TARGET_MULT,
    peers=[_PEER_MULT],
    peer_median_pe=22.0,
    peer_median_ev_to_revenue=2.8,
    peer_median_ev_to_ebitda=12.5,
)
_VALUATION_RESULT_FULL = ValuationResult(
    ticker="MRBT", assumptions=_ASSUMPTIONS, dcf=_DCF, comps=_COMPS, coverage_gaps=[]
)
_VALUATION_RESULT_THIN = ValuationResult(
    ticker="MRBT",
    assumptions=_ASSUMPTIONS,
    dcf=None,
    comps=None,
    coverage_gaps=[
        CoverageGap(field="peers", reason="insufficient peer data for SIC 3559"),
        CoverageGap(
            field="trailing_free_cash_flows",
            reason="fewer than 2 usable annual periods with both operating_cash_flow "
            "and capex present",
        ),
    ],
)

_CAPEX_FLAG = Flag(
    metric="capex_to_depreciation_ratio",
    fiscal_year=2024,
    fiscal_period="FY",
    severity=Severity.HIGH,
    description="Capex/D&A jumped to 2.8x in FY2024, driven by the new Ohio assembly facility.",
    source=SourcedFigure(
        value=2.79,
        source="ratios.capex_to_depreciation_ratio:MRBT:2024FY",
        as_of=date(2024, 12, 31),
    ),
)
_CONSOLIDATED_CAPEX = ConsolidatedFlag(
    flags=[_CAPEX_FLAG],
    summary="Capex/D&A escalated in FY2024 alongside the new Ohio facility buildout.",
)
_CAPEX_INVESTIGATION = InvestigationVerdict(
    flag=_CONSOLIDATED_CAPEX,
    verdict=VerdictType.BENIGN,
    hypothesis=(
        "The capex spike reflects a disclosed new-facility buildout, not deteriorating "
        "asset quality."
    ),
    reasoning=(
        "Company press materials and trade press both independently corroborate a new Ohio "
        "assembly facility under construction in fiscal 2024, consistent with the disclosed "
        "$120 million annual capacity addition; no evidence of unrelated asset impairment or "
        "distress was found."
    ),
    confidence=0.7,
    evidence=[
        EvidenceItem(
            url="https://www.meridianrobotics.example.com/press/ohio-facility",
            claim=(
                "Meridian Robotics announced a new Ohio assembly facility expected to add "
                "capacity in 2026."
            ),
            stance=EvidenceStance.SUPPORTS_BENIGN,
        ),
        EvidenceItem(
            url="https://www.industrialautomationnews.example.com/meridian-ohio",
            claim="Trade press independently reported construction progress on the Ohio facility.",
            stance=EvidenceStance.SUPPORTS_BENIGN,
        ),
    ],
    correlated_sibling_indices=[],
    trajectory=InvestigationTrajectory(
        search_queries=["Meridian Robotics Ohio facility capex"],
        result_urls=[
            "https://www.meridianrobotics.example.com/press/ohio-facility",
            "https://www.industrialautomationnews.example.com/meridian-ohio",
        ],
        fetched_urls=[
            "https://www.meridianrobotics.example.com/press/ohio-facility",
            "https://www.industrialautomationnews.example.com/meridian-ohio",
        ],
        distinct_domains=["meridianrobotics.example.com", "industrialautomationnews.example.com"],
    ),
    dropped_evidence=[],
    coverage_gaps=[],
)


def _input(
    *,
    valuation_result: ValuationResult,
    transcript_analyst_summary: str | None,
    consolidated_flags: list[ConsolidatedFlag],
    investigations: list[InvestigationVerdict],
    coverage_gaps: list[CoverageGap],
    sector_summary: str,
    valuation_summary: str,
) -> MemoSynthesisInput:
    return MemoSynthesisInput(
        ticker="MRBT",
        intake=_INTAKE,
        filings=_FILINGS,
        ratio_trend=_RATIO_TREND,
        financials=_FINANCIALS,
        latest_price=54.0,
        latest_price_date=date(2025, 2, 14),
        macro_bundles=_MACRO_BUNDLES,
        valuation_result=valuation_result,
        financial_analyst_summary=(
            "Revenue and net income both grew double digits in FY2024; capex/D&A rose to "
            "2.79x, flagged as a candidate anomaly given no filing-text context was "
            "available to this analyst."
        ),
        filings_analyst_summary=(
            "MD&A discloses the Ohio facility buildout as the driver of the FY2024 capex increase; "
            "no auditor change, material weakness, or restatement disclosed."
        ),
        transcript_analyst_summary=transcript_analyst_summary,
        sector_summary=sector_summary,
        macro_summary=(
            "The 10-year Treasury yield held near 4.2%, a stable rate backdrop for "
            "capital-intensive capex plans."
        ),
        valuation_summary=valuation_summary,
        consolidated_flags=consolidated_flags,
        investigations=investigations,
        coverage_gaps=coverage_gaps,
    )


_CLEAN_INPUT = _input(
    valuation_result=_VALUATION_RESULT_FULL,
    transcript_analyst_summary=(
        "No notable tone or guidance concerns; management reiterated the Ohio ramp timeline."
    ),
    consolidated_flags=[],
    investigations=[],
    coverage_gaps=[],
    sector_summary=(
        "MRBT trades at a discount to peer median P/E (19.5x vs. 22.0x) despite faster "
        "revenue growth."
    ),
    valuation_summary=(
        "Assuming a 9.7% discount rate (a 4.2% risk-free rate plus an assumed 5.5% equity risk "
        "premium), the base-case DCF present value is $540 million, above MRBT's "
        "current market value."
    ),
)

_THIN_INPUT = _input(
    valuation_result=_VALUATION_RESULT_THIN,
    transcript_analyst_summary=None,
    consolidated_flags=[],
    investigations=[],
    coverage_gaps=[
        CoverageGap(field="transcript", reason="no 8-K transcript exhibit found"),
        CoverageGap(field="peers", reason="insufficient peer data for SIC 3559"),
        CoverageGap(
            field="trailing_free_cash_flows",
            reason="fewer than 2 usable annual periods with both operating_cash_flow "
            "and capex present",
        ),
    ],
    sector_summary="Peer data for SIC 3559 was insufficient for a reliable multiples comparison.",
    valuation_summary="No trailing DCF or peer comps are available for this ticker at this time.",
)

_FLAG_INPUT = _input(
    valuation_result=_VALUATION_RESULT_FULL,
    transcript_analyst_summary="No notable tone or guidance concerns.",
    consolidated_flags=[_CONSOLIDATED_CAPEX],
    investigations=[_CAPEX_INVESTIGATION],
    coverage_gaps=[],
    sector_summary=(
        "MRBT trades at a discount to peer median P/E (19.5x vs. 22.0x) despite faster "
        "revenue growth."
    ),
    valuation_summary=(
        "Assuming a 9.7% discount rate (a 4.2% risk-free rate plus an assumed 5.5% equity risk "
        "premium), the base-case DCF present value is $540 million, above MRBT's "
        "current market value."
    ),
)


@dataclass
class MemoGroundingEvaluator(Evaluator[MemoSynthesisInput, MemoDraft, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[MemoSynthesisInput, MemoDraft, dict]
    ) -> dict[str, bool]:
        known = expand_known_numbers(known_numbers_from_synthesis_input(ctx.inputs))
        # Re-derive grounding independently from the delivered draft's own
        # sections, rather than trusting run_synthesizer_draft applied its
        # own gate correctly — same "don't just trust the module under test"
        # precedent as evals/filings.py's FilingsGroundingEvaluator.
        all_grounded = all(section_is_grounded(s, known) for s in ctx.output.sections)  # type: ignore[arg-type]
        fallback_triggered = any(
            g.reason == "numeric_grounding_check_failed" for g in ctx.output.coverage_gaps
        )
        return {"is_grounded": all_grounded, "fallback_triggered": fallback_triggered}


@dataclass
class AllTenSectionsPresentInOrder(Evaluator[MemoSynthesisInput, MemoDraft, dict]):
    def evaluate(self, ctx: EvaluatorContext[MemoSynthesisInput, MemoDraft, dict]) -> bool:
        return [s.title for s in ctx.output.sections] == list(MEMO_SECTION_ORDER)


@dataclass
class ExpectedCoverageGapPropagated(Evaluator[MemoSynthesisInput, MemoDraft, dict]):
    def evaluate(self, ctx: EvaluatorContext[MemoSynthesisInput, MemoDraft, dict]) -> bool:
        expected_substring = (ctx.metadata or {}).get("expected_coverage_gap_substring")
        if expected_substring is None:
            return True
        return any(expected_substring in g.reason for g in ctx.output.coverage_gaps)


_SUMMARY_QUALITY_RUBRIC = (
    "Each section is specific to Meridian Robotics Inc.'s real numbers and disclosed facts "
    "(the Ohio facility buildout, the 15% revenue growth, the specific margin figures) rather "
    "than generic sector commentary that could describe any industrial-automation company. The "
    "Investment Thesis section never compares against 'consensus,' 'Street expectations,' or "
    "analyst price targets (this system has no such data) -- it compares against a reverse-DCF, "
    "the company's own historical trend, or the macro backdrop instead. "
    "recommendation_and_sizing never states a dollar or percent-of-portfolio position size. If "
    "transcript_analyst_summary is null, no section fabricates management guidance or "
    "earnings-call tone commentary. If dcf or comps is null in valuation_result, the valuation "
    "section says so plainly rather than inventing the missing method."
)

dataset = Dataset(
    name="synthesizer_draft",
    cases=[
        Case(name="clean_grounded_full_coverage", inputs=_CLEAN_INPUT),
        Case(
            name="thin_data_coverage_gaps_propagate",
            inputs=_THIN_INPUT,
            metadata={"expected_coverage_gap_substring": "no 8-K transcript exhibit found"},
        ),
        Case(name="flag_and_investigation_synthesized", inputs=_FLAG_INPUT),
    ],
    evaluators=[
        MemoGroundingEvaluator(),
        AllTenSectionsPresentInOrder(),
        ExpectedCoverageGapPropagated(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=SYNTHESIZER_DRAFT_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.synthesizer_draft import run_synthesizer_draft

    report = dataset.evaluate_sync(run_synthesizer_draft)
    report.print(include_input=False, include_output=True, include_durations=True)
