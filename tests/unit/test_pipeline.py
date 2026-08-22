from contextlib import ExitStack
from datetime import date

import pytest
from pydantic_ai.models.test import TestModel

import agentic_fundamental_analyst.pipeline as pipeline_module
from agentic_fundamental_analyst.agents.filings import filings_analyst
from agentic_fundamental_analyst.agents.financial_statements import financial_statements_analyst
from agentic_fundamental_analyst.agents.macro import macro_sensitivity_analyst
from agentic_fundamental_analyst.agents.red_team import red_team
from agentic_fundamental_analyst.agents.sector import sector_analyst
from agentic_fundamental_analyst.agents.synthesizer_draft import synthesizer_draft
from agentic_fundamental_analyst.agents.synthesizer_resolve import synthesizer_resolve
from agentic_fundamental_analyst.agents.valuation_interpreter import valuation_interpreter
from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.intake import ExcludedSector, TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.memo import MEMO_SECTION_ORDER
from agentic_fundamental_analyst.contracts.prices import PriceBar, PriceHistory
from agentic_fundamental_analyst.contracts.sector_analyst import SectorPeerData
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials
from agentic_fundamental_analyst.data.fetch import TickerOutOfScope
from agentic_fundamental_analyst.pipeline import run_memo_pipeline
from agentic_fundamental_analyst.valuation import peer_multiples

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
INTAKE = TickerIntakeResult(
    ticker="TEST",
    cik="0000000000",
    sic_code="7370",
    sic_description="Software",
    in_scope=True,
    exclusion_reason=None,
)
FINANCIALS = FinancialStatementBundle(
    ticker="TEST", cik="0000000000", periods=[PERIOD], coverage_gaps=[]
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
MACRO_BUNDLES = [
    MacroSeriesBundle(
        series_id="DGS10", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=4.2)]
    ),
    MacroSeriesBundle(
        series_id="FEDFUNDS", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=4.5)]
    ),
    MacroSeriesBundle(
        series_id="T10Y2Y", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=0.3)]
    ),
]
PRICES = PriceHistory(
    ticker="TEST",
    source="tiingo",
    bars=[
        PriceBar(
            bar_date=date(2026, 8, 17),
            open=220.0,
            high=226.0,
            low=219.0,
            close=224.0,
            volume=1000,
            adj_close=224.0,
        )
    ],
)
TARGET_FINANCIALS = PeerFinancials(
    ticker="TEST",
    price=224.0,
    shares_outstanding=10.0,
    revenue=1000.0,
    net_income=100.0,
    ebitda=None,
    total_debt=500.0,
    cash_and_equivalents=50.0,
)
PEER_DATA = SectorPeerData(
    ticker="TEST",
    sic_code="7370",
    sic_description="Software",
    target=TARGET_FINANCIALS,
    peers=[],
    comps=peer_multiples(TARGET_FINANCIALS, []),
    coverage_gaps=[],
)

_NO_FLAGS = {"summary": "Clean financials, no red flags.", "flag_candidates": []}


async def _fake_fetch_all(ticker: str, price_start=None):
    return INTAKE, FINANCIALS, FILINGS, MACRO_BUNDLES, PRICES, None


async def _fake_discover_sector_peers(
    ticker, cik, sic_code, sic_description, target_price, edgar=None, price_client=None
):
    return PEER_DATA


async def _fake_fetch_all_out_of_scope(ticker: str, price_start=None):
    out_of_scope_intake = TickerIntakeResult(
        ticker=ticker,
        cik="0000000000",
        sic_code="6021",
        sic_description="National Commercial Banks",
        in_scope=False,
        exclusion_reason=ExcludedSector.BANK,
    )
    raise TickerOutOfScope(out_of_scope_intake)


async def test_run_memo_pipeline_produces_a_memo_with_all_ten_sections(monkeypatch):
    monkeypatch.setattr(pipeline_module, "fetch_all", _fake_fetch_all)
    monkeypatch.setattr(pipeline_module, "discover_sector_peers", _fake_discover_sector_peers)

    with ExitStack() as stack:
        stack.enter_context(
            financial_statements_analyst.override(model=TestModel(custom_output_args=_NO_FLAGS))
        )
        stack.enter_context(filings_analyst.override(model=TestModel(custom_output_args=_NO_FLAGS)))
        stack.enter_context(sector_analyst.override(model=TestModel()))
        stack.enter_context(macro_sensitivity_analyst.override(model=TestModel()))
        stack.enter_context(valuation_interpreter.override(model=TestModel()))
        stack.enter_context(synthesizer_draft.override(model=TestModel()))
        stack.enter_context(red_team.override(model=TestModel()))
        stack.enter_context(synthesizer_resolve.override(model=TestModel()))

        memo = await run_memo_pipeline("TEST")

    assert memo.ticker == "TEST"
    assert [s.title for s in memo.sections] == list(MEMO_SECTION_ORDER)
    assert memo.investigations == []


async def test_run_memo_pipeline_propagates_ticker_out_of_scope_unchanged(monkeypatch):
    """Regression guard: an excluded-sector ticker must still fail fast
    before any agent runs, even with Phase 5's new stages added."""
    monkeypatch.setattr(pipeline_module, "fetch_all", _fake_fetch_all_out_of_scope)

    with pytest.raises(TickerOutOfScope) as exc_info:
        await run_memo_pipeline("JPM")
    assert exc_info.value.intake.exclusion_reason == ExcludedSector.BANK
