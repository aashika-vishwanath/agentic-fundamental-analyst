from datetime import date

from pydantic import BaseModel


class CoverageGap(BaseModel):
    field: str
    reason: str


class XBRLFact(BaseModel):
    tag: str
    taxonomy: str
    unit: str
    value: float
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_period: str
    form: str
    accession_number: str
    filed_date: date


class FiscalPeriod(BaseModel):
    fiscal_year: int
    fiscal_period: str
    form: str
    period_end: date
    revenue: float | None
    net_income: float | None
    capex: float | None
    depreciation_amortization: float | None
    accounts_receivable: float | None
    inventory: float | None
    total_assets: float | None
    operating_cash_flow: float | None
    # Added beyond the PRD's illustrative sketch to support the full 8-ratio
    # Beneish M-Score (GMI, AQI, DEPI, SGAI, LVGI need these; DSRI/SGI/TATA
    # don't) — see ratios.py.
    cost_of_revenue: float | None
    sga_expense: float | None
    current_assets: float | None
    ppe_gross: float | None
    total_debt: float | None


class FinancialStatementBundle(BaseModel):
    ticker: str
    cik: str
    periods: list[FiscalPeriod]
    coverage_gaps: list[CoverageGap]
