from datetime import date

import pytest

from agentic_fundamental_analyst import ratios
from agentic_fundamental_analyst.contracts.financials import (
    CoverageGap,
    FinancialStatementBundle,
    FiscalPeriod,
)

YEAR_1 = FiscalPeriod(
    fiscal_year=2022,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2022, 12, 31),
    revenue=900.0,
    net_income=90.0,
    capex=40.0,
    depreciation_amortization=35.0,
    accounts_receivable=80.0,
    inventory=70.0,
    total_assets=1800.0,
    operating_cash_flow=110.0,
    cost_of_revenue=550.0,
    sga_expense=140.0,
    current_assets=450.0,
    ppe_gross=650.0,
    total_debt=350.0,
)

YEAR_2 = FiscalPeriod(
    fiscal_year=2023,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2023, 12, 31),
    revenue=1000.0,
    net_income=100.0,
    capex=50.0,
    depreciation_amortization=40.0,
    accounts_receivable=100.0,
    inventory=80.0,
    total_assets=2000.0,
    operating_cash_flow=120.0,
    cost_of_revenue=600.0,
    sga_expense=150.0,
    current_assets=500.0,
    ppe_gross=750.0,
    total_debt=400.0,
)

YEAR_3 = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2024, 12, 31),
    revenue=1200.0,
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

A_10Q = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="Q3",
    form="10-Q",
    period_end=date(2024, 9, 30),
    revenue=300.0,
    net_income=30.0,
    capex=20.0,
    depreciation_amortization=11.0,
    accounts_receivable=120.0,
    inventory=95.0,
    total_assets=2250.0,
    operating_cash_flow=250.0,  # deliberately YTD-shaped, to prove it gets excluded
    cost_of_revenue=170.0,
    sga_expense=45.0,
    current_assets=540.0,
    ppe_gross=880.0,
    total_debt=480.0,
)


def test_compute_trend_bundle_orders_and_pairs_consecutive_10k_periods():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000001", periods=[YEAR_3, YEAR_1, YEAR_2], coverage_gaps=[]
    )
    trend = ratios.compute_trend_bundle(bundle)

    assert [p.fiscal_year for p in trend.periods] == [2022, 2023, 2024]

    # Year 1 has no prior — growth/Beneish ratios must carry the trend-layer reason.
    year_1 = trend.periods[0]
    assert year_1.receivables_growth_vs_revenue_growth.value is None
    assert year_1.receivables_growth_vs_revenue_growth.reason == "no_prior_period_available"
    assert year_1.beneish_m_score.reason == "no_prior_period_available"
    # Single-period ratios still compute for the first period.
    assert year_1.days_sales_outstanding.value == pytest.approx(
        ratios.days_sales_outstanding(YEAR_1).value
    )

    # Year 2/3 growth ratios must match calling ratios.py directly on the same pair.
    year_2 = trend.periods[1]
    assert year_2.receivables_growth_vs_revenue_growth.value == pytest.approx(
        ratios.receivables_growth_vs_revenue_growth(YEAR_2, YEAR_1).value
    )
    assert year_2.beneish_m_score.value == pytest.approx(
        ratios.beneish_m_score(YEAR_2, YEAR_1).value
    )

    year_3 = trend.periods[2]
    assert year_3.capex_to_depreciation_ratio.value == pytest.approx(
        ratios.capex_to_depreciation_ratio(YEAR_3).value
    )
    assert year_3.inventory_growth_vs_cogs_growth.value == pytest.approx(
        ratios.inventory_growth_vs_cogs_growth(YEAR_3, YEAR_2).value
    )


def test_compute_trend_bundle_excludes_10q_periods():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000001", periods=[YEAR_1, YEAR_2, A_10Q], coverage_gaps=[]
    )
    trend = ratios.compute_trend_bundle(bundle)

    assert [p.fiscal_year for p in trend.periods] == [2022, 2023]
    assert all(p.fiscal_period == "FY" for p in trend.periods)


def test_compute_trend_bundle_single_period_is_all_coverage_gaps_for_growth_ratios():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000001", periods=[YEAR_2], coverage_gaps=[]
    )
    trend = ratios.compute_trend_bundle(bundle)

    assert len(trend.periods) == 1
    only_period = trend.periods[0]
    for growth_ratio in (
        only_period.receivables_growth_vs_revenue_growth,
        only_period.inventory_growth_vs_cogs_growth,
        only_period.beneish_m_score,
    ):
        assert growth_ratio.value is None
        assert growth_ratio.reason == "no_prior_period_available"
    # Single-period ratios are unaffected by the missing prior.
    assert only_period.cash_conversion_ratio.value == pytest.approx(
        ratios.cash_conversion_ratio(YEAR_2).value
    )


def test_compute_trend_bundle_no_10k_periods_returns_empty():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000001", periods=[A_10Q], coverage_gaps=[]
    )
    trend = ratios.compute_trend_bundle(bundle)
    assert trend.periods == []


def test_compute_trend_bundle_passes_through_coverage_gaps():
    gap = CoverageGap(field="revenue", reason="no_xbrl_tag_alias_resolved")
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000001", periods=[YEAR_2], coverage_gaps=[gap]
    )
    trend = ratios.compute_trend_bundle(bundle)
    assert trend.coverage_gaps == [gap]
