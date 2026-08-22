from datetime import date

import pytest

from agentic_fundamental_analyst import ratios
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod

PRIOR = FiscalPeriod(
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

CURRENT = FiscalPeriod(
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

EMPTY = FiscalPeriod(
    fiscal_year=2024,
    fiscal_period="FY",
    form="10-K",
    period_end=date(2024, 12, 31),
    revenue=None,
    net_income=None,
    capex=None,
    depreciation_amortization=None,
    accounts_receivable=None,
    inventory=None,
    total_assets=None,
    operating_cash_flow=None,
    cost_of_revenue=None,
    sga_expense=None,
    current_assets=None,
    ppe_gross=None,
    total_debt=None,
)


def test_days_sales_outstanding():
    assert ratios.days_sales_outstanding(CURRENT).value == pytest.approx(45.625)
    assert ratios.days_sales_outstanding(PRIOR).value == pytest.approx(36.5)


def test_days_sales_outstanding_missing_input_returns_reason():
    result = ratios.days_sales_outstanding(EMPTY)
    assert result.value is None
    assert result.reason == "accounts_receivable_or_revenue_missing"


def test_receivables_growth_vs_revenue_growth():
    # AR: 100 -> 150 (+50%), Revenue: 1000 -> 1200 (+20%), gap = 30pp
    result = ratios.receivables_growth_vs_revenue_growth(CURRENT, PRIOR)
    assert result.value == pytest.approx(0.30)


def test_inventory_growth_vs_cogs_growth():
    # Inventory: 80 -> 110 (+37.5%), COGS: 600 -> 680 (+13.33%)
    result = ratios.inventory_growth_vs_cogs_growth(CURRENT, PRIOR)
    assert result.value == pytest.approx(0.375 - (80.0 / 600.0))


def test_sloan_accruals():
    assert ratios.sloan_accruals(CURRENT).value == pytest.approx((110.0 - 100.0) / 2300.0)
    assert ratios.sloan_accruals(PRIOR).value == pytest.approx((100.0 - 120.0) / 2000.0)


def test_cash_conversion_ratio():
    assert ratios.cash_conversion_ratio(CURRENT).value == pytest.approx(100.0 / 110.0)
    assert ratios.cash_conversion_ratio(PRIOR).value == pytest.approx(1.2)


def test_capex_to_depreciation_ratio():
    assert ratios.capex_to_depreciation_ratio(CURRENT).value == pytest.approx(2.0)
    assert ratios.capex_to_depreciation_ratio(PRIOR).value == pytest.approx(1.25)


def test_cash_conversion_cycle_is_a_documented_coverage_gap():
    result = ratios.cash_conversion_cycle(CURRENT)
    assert result.value is None
    assert result.reason == "accounts_payable_not_in_fiscal_period_contract_dpo_uncomputable"


def test_zero_denominator_yields_none_not_zero():
    zero_revenue_period = CURRENT.model_copy(update={"revenue": 0.0})
    result = ratios.days_sales_outstanding(zero_revenue_period)
    assert result.value is None
    assert result.reason == "denominator_is_zero"


# --- Beneish components: independently recomputed from raw inputs, not by
# calling back into ratios.py's own helper functions ------------------------


def test_dsri_matches_independent_calculation():
    current_dso = (150.0 / 1200.0) * 365
    prior_dso = (100.0 / 1000.0) * 365
    expected = current_dso / prior_dso
    assert ratios.dsri(CURRENT, PRIOR).value == pytest.approx(expected)
    assert ratios.dsri(CURRENT, PRIOR).value == pytest.approx(1.25)


def test_gmi_matches_independent_calculation():
    current_margin = (1200.0 - 680.0) / 1200.0
    prior_margin = (1000.0 - 600.0) / 1000.0
    expected = prior_margin / current_margin
    assert ratios.gmi(CURRENT, PRIOR).value == pytest.approx(expected)


def test_aqi_matches_independent_calculation():
    current_q = 1 - (560.0 + 900.0) / 2300.0
    prior_q = 1 - (500.0 + 750.0) / 2000.0
    expected = current_q / prior_q
    assert ratios.aqi(CURRENT, PRIOR).value == pytest.approx(expected)


def test_sgi_matches_independent_calculation():
    assert ratios.sgi(CURRENT, PRIOR).value == pytest.approx(1200.0 / 1000.0)


def test_depi_matches_independent_calculation():
    current_rate = 45.0 / (45.0 + 900.0)
    prior_rate = 40.0 / (40.0 + 750.0)
    expected = prior_rate / current_rate
    assert ratios.depi(CURRENT, PRIOR).value == pytest.approx(expected)


def test_sgai_matches_independent_calculation():
    current_ratio = 190.0 / 1200.0
    prior_ratio = 150.0 / 1000.0
    expected = current_ratio / prior_ratio
    assert ratios.sgai(CURRENT, PRIOR).value == pytest.approx(expected)


def test_lvgi_matches_independent_calculation():
    current_lev = 500.0 / 2300.0
    prior_lev = 400.0 / 2000.0
    expected = current_lev / prior_lev
    assert ratios.lvgi(CURRENT, PRIOR).value == pytest.approx(expected)


def test_tata_equals_sloan_accruals():
    assert ratios.tata(CURRENT).value == ratios.sloan_accruals(CURRENT).value


def test_beneish_m_score_matches_independent_weighted_sum():
    dsri = (150.0 / 1200.0 * 365) / (100.0 / 1000.0 * 365)
    gmi = ((1000.0 - 600.0) / 1000.0) / ((1200.0 - 680.0) / 1200.0)
    aqi = (1 - (560.0 + 900.0) / 2300.0) / (1 - (500.0 + 750.0) / 2000.0)
    sgi = 1200.0 / 1000.0
    depi = (40.0 / (40.0 + 750.0)) / (45.0 / (45.0 + 900.0))
    sgai = (190.0 / 1200.0) / (150.0 / 1000.0)
    lvgi = (500.0 / 2300.0) / (400.0 / 2000.0)
    tata = (110.0 - 100.0) / 2300.0

    expected = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )

    result = ratios.beneish_m_score(CURRENT, PRIOR)
    assert result.value == pytest.approx(expected)


def test_beneish_m_score_reports_which_components_are_missing():
    result = ratios.beneish_m_score(EMPTY, PRIOR)
    assert result.value is None
    assert result.reason is not None
    assert result.reason.startswith("components_unavailable:")
    for component in ("aqi", "depi", "dsri", "gmi", "lvgi", "sgai", "sgi", "tata"):
        assert component in result.reason


# --- build_company_macro_profile (Phase 5) --------------------------------


def test_build_company_macro_profile_full_data():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000000", periods=[PRIOR, CURRENT], coverage_gaps=[]
    )
    profile = ratios.build_company_macro_profile("TEST", "Software", bundle)
    assert profile.ticker == "TEST"
    assert profile.sic_description == "Software"
    assert profile.latest_revenue == 1200.0
    assert profile.latest_total_debt == 500.0
    years = (CURRENT.period_end - PRIOR.period_end).days / 365.0
    expected_cagr = (1200.0 / 1000.0) ** (1 / years) - 1
    assert profile.revenue_cagr == pytest.approx(expected_cagr)


def test_build_company_macro_profile_missing_total_debt_does_not_blank_revenue():
    current_no_debt = CURRENT.model_copy(update={"total_debt": None})
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000000", periods=[PRIOR, current_no_debt], coverage_gaps=[]
    )
    profile = ratios.build_company_macro_profile("TEST", "Software", bundle)
    assert profile.latest_revenue == 1200.0
    assert profile.latest_total_debt is None
    assert profile.revenue_cagr is not None


def test_build_company_macro_profile_fewer_than_two_annual_periods():
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000000", periods=[CURRENT], coverage_gaps=[]
    )
    profile = ratios.build_company_macro_profile("TEST", "Software", bundle)
    assert profile.latest_revenue == 1200.0
    assert profile.revenue_cagr is None


def test_build_company_macro_profile_zero_annual_periods():
    ten_q = CURRENT.model_copy(update={"form": "10-Q"})
    bundle = FinancialStatementBundle(
        ticker="TEST", cik="0000000000", periods=[ten_q], coverage_gaps=[]
    )
    profile = ratios.build_company_macro_profile("TEST", "Software", bundle)
    assert profile.latest_revenue is None
    assert profile.latest_total_debt is None
    assert profile.revenue_cagr is None
