from datetime import date

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class RatioResult(BaseModel):
    value: float | None
    reason: str | None = None  # populated only when value is None


class PeriodRatios(BaseModel):
    fiscal_year: int
    fiscal_period: str
    period_end: date
    days_sales_outstanding: RatioResult
    receivables_growth_vs_revenue_growth: RatioResult
    inventory_growth_vs_cogs_growth: RatioResult
    sloan_accruals: RatioResult
    cash_conversion_ratio: RatioResult
    capex_to_depreciation_ratio: RatioResult
    days_inventory_outstanding: RatioResult  # intermediate; not independently flaggable
    cash_conversion_cycle: RatioResult  # always None — see ratios.py module docstring
    beneish_m_score: RatioResult
    # raw values carried through so the agent's narrative can cite real magnitudes
    revenue: float | None
    net_income: float | None
    capex: float | None
    depreciation_amortization: float | None


class RatioTrendBundle(BaseModel):
    ticker: str
    cik: str
    periods: list[PeriodRatios]  # chronological, oldest first, 10-K/annual only
    coverage_gaps: list[CoverageGap]
