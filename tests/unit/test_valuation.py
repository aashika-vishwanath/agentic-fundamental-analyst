from datetime import date

import pytest

from agentic_fundamental_analyst import valuation
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials

CASH_FLOWS = [100.0, 110.0, 121.0]
DISCOUNT_RATE = 0.10
TERMINAL_GROWTH = 0.03


def _independent_pv(cash_flows: list[float], r: float, g: float) -> float:
    """Reimplemented independently from valuation.py's own _present_value,
    as a real cross-check rather than trusting the module under test."""
    pv = 0.0
    for t, cf in enumerate(cash_flows, start=1):
        pv += cf / ((1 + r) ** t)
    terminal_value = cash_flows[-1] * (1 + g) / (r - g)
    pv += terminal_value / ((1 + r) ** len(cash_flows))
    return pv


def test_dcf_base_case_matches_independent_calculation():
    result = valuation.dcf(CASH_FLOWS, DISCOUNT_RATE, TERMINAL_GROWTH)
    base = next(s for s in result.scenarios if s.label == "base")
    expected = _independent_pv(CASH_FLOWS, DISCOUNT_RATE, TERMINAL_GROWTH)
    assert base.present_value == pytest.approx(expected)
    assert base.discount_rate == pytest.approx(0.10)
    assert base.terminal_growth == pytest.approx(0.03)


def test_dcf_bull_and_bear_scenarios_bracket_base():
    result = valuation.dcf(CASH_FLOWS, DISCOUNT_RATE, TERMINAL_GROWTH)
    by_label = {s.label: s for s in result.scenarios}

    bull_expected = _independent_pv(CASH_FLOWS, 0.09, 0.035)
    bear_expected = _independent_pv(CASH_FLOWS, 0.11, 0.025)

    assert by_label["bull"].present_value == pytest.approx(bull_expected)
    assert by_label["bear"].present_value == pytest.approx(bear_expected)
    # Lower discount rate + higher terminal growth -> higher PV, and vice versa
    assert by_label["bull"].present_value is not None
    assert by_label["base"].present_value is not None
    assert by_label["bear"].present_value is not None
    assert by_label["bull"].present_value > by_label["base"].present_value
    assert by_label["bear"].present_value < by_label["base"].present_value


def test_dcf_invalid_when_discount_rate_at_or_below_terminal_growth():
    result = valuation.dcf(CASH_FLOWS, discount_rate=0.03, terminal_growth=0.03)
    base = next(s for s in result.scenarios if s.label == "base")
    assert base.present_value is None


def test_dcf_empty_cash_flows_yields_none_not_zero():
    result = valuation.dcf([], DISCOUNT_RATE, TERMINAL_GROWTH)
    assert all(s.present_value is None for s in result.scenarios)


TARGET = PeerFinancials(
    ticker="TARGET",
    price=100.0,
    shares_outstanding=10.0,  # market cap 1,000
    revenue=500.0,
    net_income=50.0,
    ebitda=100.0,
    total_debt=200.0,
    cash_and_equivalents=50.0,
)

PEER_A = PeerFinancials(
    ticker="PEER_A",
    price=50.0,
    shares_outstanding=20.0,  # market cap 1,000
    revenue=400.0,
    net_income=40.0,
    ebitda=80.0,
    total_debt=100.0,
    cash_and_equivalents=100.0,
)

PEER_B = PeerFinancials(
    ticker="PEER_B",
    price=200.0,
    shares_outstanding=5.0,  # market cap 1,000
    revenue=None,  # missing revenue -> ev_to_revenue must be None, not 0
    net_income=100.0,
    ebitda=200.0,
    total_debt=0.0,
    cash_and_equivalents=0.0,
)


def test_peer_multiples_target_computed_correctly():
    result = valuation.peer_multiples(TARGET, [PEER_A, PEER_B])
    # market_cap = 1000, EV = 1000 + 200 - 50 = 1150
    assert result.target.pe_ratio == pytest.approx(1000.0 / 50.0)
    assert result.target.ev_to_revenue == pytest.approx(1150.0 / 500.0)
    assert result.target.ev_to_ebitda == pytest.approx(1150.0 / 100.0)


def test_peer_multiples_missing_field_yields_none_not_zero():
    result = valuation.peer_multiples(TARGET, [PEER_A, PEER_B])
    peer_b = next(p for p in result.peers if p.ticker == "PEER_B")
    assert peer_b.ev_to_revenue is None
    assert peer_b.pe_ratio == pytest.approx(1000.0 / 100.0)


def test_peer_median_ignores_none_values():
    result = valuation.peer_multiples(TARGET, [PEER_A, PEER_B])
    # peer_a ev_to_revenue = (1000+100-100)/400 = 2.5; peer_b's is None and excluded
    assert result.peer_median_ev_to_revenue == pytest.approx(2.5)


def _annual_period(
    fiscal_year: int, operating_cash_flow: float | None, capex: float | None
) -> FiscalPeriod:
    return FiscalPeriod(
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        form="10-K",
        period_end=date(fiscal_year, 12, 31),
        revenue=None,
        net_income=None,
        capex=capex,
        depreciation_amortization=None,
        accounts_receivable=None,
        inventory=None,
        total_assets=None,
        operating_cash_flow=operating_cash_flow,
        cost_of_revenue=None,
        sga_expense=None,
        current_assets=None,
        ppe_gross=None,
        total_debt=None,
    )


def test_trailing_free_cash_flows_oldest_first_annual_only():
    bundle = FinancialStatementBundle(
        ticker="TEST",
        cik="0000000001",
        periods=[
            _annual_period(2024, operating_cash_flow=150.0, capex=50.0),
            _annual_period(2022, operating_cash_flow=100.0, capex=40.0),
            _annual_period(2023, operating_cash_flow=120.0, capex=45.0),
            FiscalPeriod(
                fiscal_year=2024,
                fiscal_period="Q3",
                form="10-Q",
                period_end=date(2024, 9, 30),
                revenue=None,
                net_income=None,
                capex=10.0,
                depreciation_amortization=None,
                accounts_receivable=None,
                inventory=None,
                total_assets=None,
                operating_cash_flow=30.0,
                cost_of_revenue=None,
                sga_expense=None,
                current_assets=None,
                ppe_gross=None,
                total_debt=None,
            ),
        ],
        coverage_gaps=[],
    )
    flows = valuation.trailing_free_cash_flows(bundle)
    assert flows == [60.0, 75.0, 100.0]  # 2022, 2023, 2024 — 10-Q excluded


def test_trailing_free_cash_flows_none_when_fewer_than_two_usable_periods():
    bundle = FinancialStatementBundle(
        ticker="TEST",
        cik="0000000001",
        periods=[
            _annual_period(2024, operating_cash_flow=150.0, capex=50.0),
            _annual_period(2023, operating_cash_flow=None, capex=45.0),  # missing OCF
        ],
        coverage_gaps=[],
    )
    assert valuation.trailing_free_cash_flows(bundle) is None


def test_build_valuation_assumptions_uses_latest_non_none_dgs10_point():
    macro = [
        MacroSeriesBundle(
            series_id="DGS10",
            points=[
                MacroSeriesPoint(obs_date=date(2026, 8, 17), value=4.20),
                MacroSeriesPoint(obs_date=date(2026, 8, 18), value=None),  # FRED "." sentinel
                MacroSeriesPoint(obs_date=date(2026, 8, 16), value=4.10),
            ],
        ),
        MacroSeriesBundle(series_id="FEDFUNDS", points=[]),
    ]
    assumptions = valuation.build_valuation_assumptions(macro)
    assert assumptions is not None
    assert assumptions.risk_free_rate == pytest.approx(0.042)
    assert assumptions.risk_free_rate_as_of == date(2026, 8, 17)
    assert assumptions.discount_rate == pytest.approx(0.042 + valuation._EQUITY_RISK_PREMIUM)
    assert assumptions.terminal_growth == pytest.approx(valuation._TERMINAL_GROWTH_ASSUMPTION)


def test_build_valuation_assumptions_none_when_dgs10_missing():
    macro = [MacroSeriesBundle(series_id="FEDFUNDS", points=[])]
    assert valuation.build_valuation_assumptions(macro) is None


def test_build_valuation_assumptions_none_when_dgs10_all_none():
    macro = [
        MacroSeriesBundle(
            series_id="DGS10", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=None)]
        )
    ]
    assert valuation.build_valuation_assumptions(macro) is None
