from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.synthesizer_draft import (
    run_synthesizer_draft,
    synthesizer_draft,
)
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import (
    MEMO_SECTION_ORDER,
    SynthesizerDraftAgentOutput,
)
from agentic_fundamental_analyst.contracts.ratios import PeriodRatios, RatioResult, RatioTrendBundle
from agentic_fundamental_analyst.contracts.synthesis import MemoSynthesisInput
from agentic_fundamental_analyst.contracts.valuation import (
    DCFResult,
    DCFScenario,
    PeerCompsResult,
    PeerMultiples,
    ValuationAssumptions,
    ValuationResult,
)

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
DCF = DCFResult(
    cash_flows=[100.0],
    scenarios=[
        DCFScenario(label="base", discount_rate=0.097, terminal_growth=0.025, present_value=1234.5)
    ],
)
TARGET_MULT = PeerMultiples(ticker="TEST", pe_ratio=22.4, ev_to_revenue=5.0, ev_to_ebitda=None)
COMPS = PeerCompsResult(
    target=TARGET_MULT,
    peers=[],
    peer_median_pe=18.1,
    peer_median_ev_to_revenue=None,
    peer_median_ev_to_ebitda=None,
)
VALUATION_RESULT = ValuationResult(
    ticker="TEST", assumptions=ASSUMPTIONS, dcf=DCF, comps=COMPS, coverage_gaps=[]
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

INPUT = MemoSynthesisInput(
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
    filings_analyst_summary="No red flags in the filing text.",
    transcript_analyst_summary=None,
    sector_summary="In line with peers.",
    macro_summary="Rates are stable.",
    valuation_summary="Trades near DCF fair value.",
    consolidated_flags=[],
    investigations=[],
    coverage_gaps=[],
)


def _section(title: str, content: str) -> dict:
    return {"title": title, "content": content, "cited_figures": [], "cited_quotes": []}


def test_agent_default_test_model_produces_valid_output_type():
    with synthesizer_draft.override(model=TestModel()):
        result = synthesizer_draft.run_sync(INPUT.model_dump_json())
    assert isinstance(result.output, SynthesizerDraftAgentOutput)


async def test_run_synthesizer_draft_keeps_grounded_content_for_all_ten_sections():
    scripted = {
        "rating": "buy",
        "conviction": "medium",
        "sections": [
            _section(title, f"Revenue reached 1000.0 in FY2024 for the {title} section.")
            for title in MEMO_SECTION_ORDER
        ],
    }
    with synthesizer_draft.override(model=TestModel(custom_output_args=scripted)):
        draft = await run_synthesizer_draft(INPUT)

    assert [s.title for s in draft.sections] == list(MEMO_SECTION_ORDER)
    assert draft.coverage_gaps == []
    assert all("numeric-grounding check" not in s.content for s in draft.sections)


async def test_run_synthesizer_draft_falls_back_only_the_offending_section():
    sections = [
        _section(title, "A clean, non-numeric qualitative claim.") for title in MEMO_SECTION_ORDER
    ]
    for s in sections:
        if s["title"] == "valuation":
            s["content"] = "A fabricated value of 8675309.0 appears here."
    scripted = {"rating": "hold", "conviction": "low", "sections": sections}
    with synthesizer_draft.override(model=TestModel(custom_output_args=scripted)):
        draft = await run_synthesizer_draft(INPUT)

    valuation_section = next(s for s in draft.sections if s.title == "valuation")
    other_section = next(s for s in draft.sections if s.title == "business_overview")
    assert "numeric-grounding check" in valuation_section.content
    assert other_section.content == "A clean, non-numeric qualitative claim."
    assert any(g.field == "section:valuation" for g in draft.coverage_gaps)


async def test_run_synthesizer_draft_fills_missing_section_with_placeholder():
    incomplete = [t for t in MEMO_SECTION_ORDER if t != "catalysts"]
    scripted = {
        "rating": "hold",
        "conviction": "low",
        "sections": [_section(title, "Qualitative content, no numbers.") for title in incomplete],
    }
    with synthesizer_draft.override(model=TestModel(custom_output_args=scripted)):
        draft = await run_synthesizer_draft(INPUT)

    assert [s.title for s in draft.sections] == list(MEMO_SECTION_ORDER)
    catalysts_section = next(s for s in draft.sections if s.title == "catalysts")
    assert "not produced" in catalysts_section.content
    assert any(g.reason == "section_missing_from_draft" for g in draft.coverage_gaps)
