from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.synthesizer_resolve import (
    run_synthesizer_resolve,
    synthesizer_resolve,
)
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import (
    MEMO_SECTION_ORDER,
    Attack,
    MemoDraft,
    MemoSection,
    RedTeamAttack,
    SynthesizerResolveAgentOutput,
)
from agentic_fundamental_analyst.contracts.ratios import PeriodRatios, RatioResult, RatioTrendBundle
from agentic_fundamental_analyst.contracts.synthesis import (
    MemoSynthesisInput,
    SynthesizerResolveInput,
)
from agentic_fundamental_analyst.contracts.valuation import ValuationAssumptions, ValuationResult

PERIOD = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2024, 12, 31),
    revenue=1000.0,
    net_income=100.0,
    capex=90.0,
    depreciation_amortization=45.0,
    accounts_receivable=150.0,
    inventory=110.0,
    total_assets=2300.0,
    operating_cash_flow=100.0,
    cost_of_revenue=680.0,
    sga_expense=190.0,
    current_assets=560.0,
    ppe_gross=900.0,
    total_debt=500.0,
)
RATIO_PERIOD = PeriodRatios(
    fiscal_year=2024,
    fiscal_period="FY",
    period_end=date(2024, 12, 31),
    days_sales_outstanding=RatioResult(value=45.6),
    receivables_growth_vs_revenue_growth=RatioResult(value=0.05),
    inventory_growth_vs_cogs_growth=RatioResult(value=0.02),
    sloan_accruals=RatioResult(value=0.01),
    cash_conversion_ratio=RatioResult(value=0.9),
    capex_to_depreciation_ratio=RatioResult(value=2.0),
    days_inventory_outstanding=RatioResult(value=59.0),
    cash_conversion_cycle=RatioResult(
        value=None, reason="accounts_payable_not_in_fiscal_period_contract_dpo_uncomputable"
    ),
    beneish_m_score=RatioResult(value=-2.1),
    revenue=1000.0,
    net_income=100.0,
    capex=90.0,
    depreciation_amortization=45.0,
)
ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2026, 8, 17),
    equity_risk_premium=0.055,
    discount_rate=0.097,
    terminal_growth=0.025,
)
VALUATION_RESULT = ValuationResult(
    ticker="TEST", assumptions=ASSUMPTIONS, dcf=None, comps=None, coverage_gaps=[]
)
FILINGS = FilingSections(
    accession_number="0001-24-000001",
    filed_date=date(2024, 2, 20),
    period_of_report=date(2023, 12, 31),
    item_1_business="TEST sells widgets across North America.",
    item_1a_risk_factors=None,
    item_7_mdna=None,
    item_9a_controls=None,
    eightk_item_bodies={},
    eightk_item_sources={},
    coverage_gaps=[],
)
INTAKE = TickerIntakeResult(
    ticker="TEST",
    cik="0000000000",
    sic_code="7370",
    sic_description="Software",
    in_scope=True,
    exclusion_reason=None,
)

SYNTHESIS_INPUT = MemoSynthesisInput(
    ticker="TEST",
    intake=INTAKE,
    filings=FILINGS,
    ratio_trend=RatioTrendBundle(
        ticker="TEST", cik="0000000000", periods=[RATIO_PERIOD], coverage_gaps=[]
    ),
    financials=FinancialStatementBundle(
        ticker="TEST", cik="0000000000", periods=[PERIOD], coverage_gaps=[]
    ),
    latest_price=224.0,
    latest_price_date=date(2026, 8, 17),
    macro_bundles=[
        MacroSeriesBundle(
            series_id="DGS10", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=4.2)]
        )
    ],
    valuation_result=VALUATION_RESULT,
    financial_analyst_summary="Clean financials.",
    filings_analyst_summary="No red flags.",
    transcript_analyst_summary=None,
    sector_summary="In line with peers.",
    macro_summary="Rates are stable.",
    valuation_summary="No DCF or comps available.",
    consolidated_flags=[],
    investigations=[],
    coverage_gaps=[],
)


def _draft_section(title: str, content: str) -> MemoSection:
    return MemoSection(title=title, content=content, cited_figures=[], cited_quotes=[])  # type: ignore[arg-type]


DRAFT = MemoDraft(
    ticker="TEST",
    rating="hold",  # type: ignore[arg-type]
    conviction="medium",  # type: ignore[arg-type]
    sections=[
        _draft_section(title, "Qualitative content, no numbers.") for title in MEMO_SECTION_ORDER
    ],
    coverage_gaps=[],
)

ONE_ATTACK = RedTeamAttack(
    attacks=[
        Attack(
            section="investment_thesis",  # type: ignore[arg-type]
            category="boilerplate",  # type: ignore[arg-type]
            quoted_claim="Qualitative content, no numbers.",
            critique="No falsifiable trigger.",
            checklist_item=None,
        )
    ],
    dropped_candidates=[],
)

RESOLVE_INPUT = SynthesizerResolveInput(
    draft=DRAFT, red_team=ONE_ATTACK, synthesis_input=SYNTHESIS_INPUT
)


def _section(title: str, content: str) -> dict:
    return {"title": title, "content": content, "cited_figures": [], "cited_quotes": []}


def test_agent_default_test_model_produces_valid_output_type():
    with synthesizer_resolve.override(model=TestModel()):
        result = synthesizer_resolve.run_sync(RESOLVE_INPUT.model_dump_json())
    assert isinstance(result.output, SynthesizerResolveAgentOutput)


async def test_run_synthesizer_resolve_every_attack_gets_a_real_resolution():
    scripted = {
        "resolutions": [
            {
                "attack_index": 0,
                "resolution": "downgraded",
                "explanation": "Reframed as a stated assumption, not a hard fact.",
                "model_addressed": True,
            }
        ],
        "rating": "hold",
        "conviction": "low",
        "sections": [
            _section(title, "Rewritten qualitative content.") for title in MEMO_SECTION_ORDER
        ],
    }
    with synthesizer_resolve.override(model=TestModel(custom_output_args=scripted)):
        memo = await run_synthesizer_resolve(RESOLVE_INPUT)

    assert len(memo.resolutions) == 1
    assert memo.resolutions[0].model_addressed is True
    assert memo.resolutions[0].resolution.value == "downgraded"


async def test_run_synthesizer_resolve_fills_missing_resolution_with_fallback():
    scripted = {
        "resolutions": [],
        "rating": "hold",
        "conviction": "low",
        "sections": [
            _section(title, "Rewritten qualitative content.") for title in MEMO_SECTION_ORDER
        ],
    }
    with synthesizer_resolve.override(model=TestModel(custom_output_args=scripted)):
        memo = await run_synthesizer_resolve(RESOLVE_INPUT)

    assert len(memo.resolutions) == 1
    assert memo.resolutions[0].model_addressed is False
    assert memo.resolutions[0].attack_index == 0


async def test_run_synthesizer_resolve_reapplies_grounding_gate_on_rewritten_sections():
    sections = [_section(title, "Clean qualitative content.") for title in MEMO_SECTION_ORDER]
    for s in sections:
        if s["title"] == "valuation":
            s["content"] = "A fabricated figure of 9999999.0 reappears here."
    scripted = {
        "resolutions": [
            {
                "attack_index": 0,
                "resolution": "downgraded",
                "explanation": "Reframed.",
                "model_addressed": True,
            }
        ],
        "rating": "hold",
        "conviction": "low",
        "sections": sections,
    }
    with synthesizer_resolve.override(model=TestModel(custom_output_args=scripted)):
        memo = await run_synthesizer_resolve(RESOLVE_INPUT)

    valuation_section = next(s for s in memo.sections if s.title == "valuation")
    assert "numeric-grounding check" in valuation_section.content
    assert any(g.field == "section:valuation" for g in memo.coverage_gaps)


async def test_run_synthesizer_resolve_carries_investigations_through_unchanged():
    scripted = {
        "resolutions": [
            {
                "attack_index": 0,
                "resolution": "cut",
                "explanation": "Removed.",
                "model_addressed": True,
            }
        ],
        "rating": "hold",
        "conviction": "low",
        "sections": [_section(title, "Rewritten content.") for title in MEMO_SECTION_ORDER],
    }
    with synthesizer_resolve.override(model=TestModel(custom_output_args=scripted)):
        memo = await run_synthesizer_resolve(RESOLVE_INPUT)

    assert memo.investigations == SYNTHESIS_INPUT.investigations
