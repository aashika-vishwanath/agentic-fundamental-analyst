from datetime import date

from agentic_fundamental_analyst.agents.memo_grounding import (
    apply_grounding_gate,
    known_numbers_from_synthesis_input,
)
from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import MemoSectionAgentOutput
from agentic_fundamental_analyst.contracts.ratios import PeriodRatios, RatioResult, RatioTrendBundle
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

PERIOD = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2024, 12, 31),
    revenue=1981700.0,
    net_income=110.0,
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
    revenue=1981700.0,
    net_income=110.0,
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

# Deliberately exercises three of test_numeric_grounding.py's six regression
# categories through the larger MemoSynthesisInput surface: a comma-thousands
# number ($1,981,700), an ISO date (2029-03-15), and a "10-year" label -- the
# real number must be harvested, the date/label must not pollute the set with
# spurious values.
FILINGS = FilingSections(
    accession_number="0001-24-000001",
    filed_date=date(2024, 2, 20),
    period_of_report=date(2023, 12, 31),
    item_1_business=(
        "The Company disclosed a debt maturity of $1,981,700 due 2029-03-15, "
        "backed by a 10-year credit facility."
    ),
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


_BASE_INPUT = MemoSynthesisInput(
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
    financial_analyst_summary="",
    filings_analyst_summary="",
    transcript_analyst_summary=None,
    sector_summary="",
    macro_summary="",
    valuation_summary="",
    consolidated_flags=[],
    investigations=[],
    coverage_gaps=[],
)


def _input(**overrides: object) -> MemoSynthesisInput:
    return _BASE_INPUT.model_copy(update=overrides)


def test_known_numbers_harvests_comma_thousands_number_from_filing_prose():
    known = known_numbers_from_synthesis_input(_input())
    assert 1981700.0 in known


def test_known_numbers_does_not_mis_split_iso_date_or_year_label():
    known = known_numbers_from_synthesis_input(_input())
    # A plain digit-run pattern applied naively would extract 2029, -3, -15
    # from "2029-03-15" -- none of those should show up as spurious entries
    # distinct from the real harvested numbers.
    assert -3.0 not in known
    assert -15.0 not in known


def test_known_numbers_harvests_number_from_consolidated_flag_description():
    flag = Flag(
        metric="capex_to_depreciation_ratio",
        fiscal_year=2024,
        fiscal_period="FY",
        severity=Severity.MEDIUM,
        description="AR grew 654321.0 versus revenue growth of 9%.",
        source=SourcedFigure(value=4.3, source="ratios.x", as_of=date(2024, 12, 31)),
    )
    consolidated = ConsolidatedFlag(flags=[flag], summary="Capex escalation.")
    known = known_numbers_from_synthesis_input(_input(consolidated_flags=[consolidated]))
    assert 654321.0 in known
    assert 4.3 in known  # the flag's own SourcedFigure value


def test_apply_grounding_gate_keeps_grounded_section_and_its_real_citation():
    section = MemoSectionAgentOutput(
        title="financial_analysis",
        content="Revenue reached 1,981,700 in FY2024, with capex/D&A at 2.0x.",
        cited_figures=[
            SourcedFigure(
                value=1981700.0, source="financials.revenue:TEST:2024FY", as_of=date(2024, 12, 31)
            )
        ],
    )
    known = known_numbers_from_synthesis_input(_input())
    grounded, gaps = apply_grounding_gate([section], known)
    assert grounded[0].content == section.content
    assert gaps == []


def test_apply_grounding_gate_falls_back_on_fabricated_content_number():
    section = MemoSectionAgentOutput(
        title="valuation",
        content="The DCF implies a wildly optimistic value of 8675309.0 per share.",
        cited_figures=[],
    )
    known = known_numbers_from_synthesis_input(_input())
    grounded, gaps = apply_grounding_gate([section], known)
    assert grounded[0].content != section.content
    assert "not pass the numeric-grounding check" in grounded[0].content
    assert len(gaps) == 1
    assert gaps[0].field == "section:valuation"
    assert gaps[0].reason == "numeric_grounding_check_failed"


def test_apply_grounding_gate_falls_back_on_fabricated_cited_figure_even_with_clean_content():
    section = MemoSectionAgentOutput(
        title="appendix_and_sourcing",
        content="See the cited figure below for the sourced revenue value.",
        cited_figures=[
            SourcedFigure(value=99999999.0, source="fabricated.source", as_of=date(2024, 12, 31))
        ],
    )
    known = known_numbers_from_synthesis_input(_input())
    grounded, gaps = apply_grounding_gate([section], known)
    assert grounded[0].content != section.content
    assert len(gaps) == 1


def test_apply_grounding_gate_only_falls_back_the_offending_section():
    good = MemoSectionAgentOutput(
        title="financial_analysis", content="Revenue reached 1,981,700 in FY2024.", cited_figures=[]
    )
    bad = MemoSectionAgentOutput(
        title="valuation", content="A fabricated figure of 424242.0 appears here.", cited_figures=[]
    )
    known = known_numbers_from_synthesis_input(_input())
    grounded, gaps = apply_grounding_gate([good, bad], known)
    assert grounded[0].content == good.content
    assert grounded[1].content != bad.content
    assert len(gaps) == 1
    assert gaps[0].field == "section:valuation"
