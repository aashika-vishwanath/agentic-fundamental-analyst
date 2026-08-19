from datetime import date

import pytest
from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.financial_statements import (
    _ratio_unavailable_gaps,
    financial_statements_analyst,
    run_financial_statements_analyst,
)
from agentic_fundamental_analyst.contracts.financial_analyst import FinancialAnalystAgentOutput
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.ratios import compute_trend_bundle

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

SINGLE_PERIOD_BUNDLE = FinancialStatementBundle(
    ticker="TEST", cik="0000000001", periods=[CURRENT], coverage_gaps=[]
)

TWO_PERIOD_BUNDLE = FinancialStatementBundle(
    ticker="TEST", cik="0000000001", periods=[PRIOR, CURRENT], coverage_gaps=[]
)


def test_agent_default_test_model_produces_valid_output_type():
    with financial_statements_analyst.override(model=TestModel()):
        result = financial_statements_analyst.run_sync(
            compute_trend_bundle(TWO_PERIOD_BUNDLE).model_dump_json()
        )
    assert isinstance(result.output, FinancialAnalystAgentOutput)


async def test_run_financial_statements_analyst_grounds_real_candidate_and_drops_fake_one():
    scripted_output = {
        "summary": "Revenue and margins grew year over year.",
        "flag_candidates": [
            {
                # Real: days_sales_outstanding has a value for fiscal_year=2024/FY.
                "metric": "days_sales_outstanding",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "severity": "medium",
                "description": "DSO extended year over year.",
            },
            {
                # Fake: no such fiscal year exists in the bundle at all.
                "metric": "beneish_m_score",
                "fiscal_year": 1999,
                "fiscal_period": "FY",
                "severity": "high",
                "description": "Hallucinated period.",
            },
        ],
    }
    with financial_statements_analyst.override(
        model=TestModel(custom_output_args=scripted_output)
    ):
        result = await run_financial_statements_analyst(TWO_PERIOD_BUNDLE)

    assert len(result.flags) == 1
    real_flag = result.flags[0]
    assert real_flag.metric == "days_sales_outstanding"
    assert real_flag.fiscal_year == 2024
    trend = compute_trend_bundle(TWO_PERIOD_BUNDLE)
    expected_value = trend.periods[-1].days_sales_outstanding.value
    assert real_flag.source.value == pytest.approx(expected_value)
    assert real_flag.source.source == "ratios.days_sales_outstanding:TEST:2024FY"
    assert real_flag.source.as_of == date(2024, 12, 31)

    assert len(result.dropped_candidates) == 1
    assert "beneish_m_score" in result.dropped_candidates[0]
    assert "1999" in result.dropped_candidates[0]


async def test_run_financial_statements_analyst_drops_candidate_referencing_unavailable_value():
    scripted_output = {
        "summary": "Only one year of history is available.",
        "flag_candidates": [
            {
                # beneish_m_score is structurally unavailable in a single-period bundle
                # (no prior period) even though the period itself is real.
                "metric": "beneish_m_score",
                "fiscal_year": 2024,
                "fiscal_period": "FY",
                "severity": "low",
                "description": "Should be dropped, not grounded.",
            }
        ],
    }
    with financial_statements_analyst.override(
        model=TestModel(custom_output_args=scripted_output)
    ):
        result = await run_financial_statements_analyst(SINGLE_PERIOD_BUNDLE)

    assert result.flags == []
    assert len(result.dropped_candidates) == 1


def test_ratio_unavailable_gaps_covers_every_missing_metric_in_single_period_bundle():
    trend = compute_trend_bundle(SINGLE_PERIOD_BUNDLE)
    gaps = _ratio_unavailable_gaps(trend)
    gap_fields = {gap.field for gap in gaps}

    for metric in (
        "receivables_growth_vs_revenue_growth",
        "inventory_growth_vs_cogs_growth",
        "beneish_m_score",
    ):
        assert f"{metric}:2024FY" in gap_fields
    for gap in gaps:
        assert gap.reason == "no_prior_period_available"

    # Single-period ratios (DSO, cash conversion, capex/D&A) are available and
    # must NOT show up as gaps.
    assert "days_sales_outstanding:2024FY" not in gap_fields
    assert "cash_conversion_ratio:2024FY" not in gap_fields
