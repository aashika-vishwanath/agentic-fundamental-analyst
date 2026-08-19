from typing import Literal

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Flag, Severity

FinancialFlagMetric = Literal[
    "days_sales_outstanding",
    "receivables_growth_vs_revenue_growth",
    "inventory_growth_vs_cogs_growth",
    "sloan_accruals",
    "cash_conversion_ratio",
    "capex_to_depreciation_ratio",
    "beneish_m_score",
]
# Deliberately excludes days_inventory_outstanding (intermediate only) and
# cash_conversion_cycle (permanently unavailable — see ratios.py module docstring).


class FlagCandidate(BaseModel):
    metric: FinancialFlagMetric
    fiscal_year: int
    fiscal_period: str
    severity: Severity
    description: str
    # No `value` field: the agent names what it thinks is flag-worthy: the
    # deterministic grounding pass supplies and verifies the real number.


class FinancialAnalystAgentOutput(BaseModel):
    """The agent's own output_type — narrower than the final stage output."""

    summary: str
    flag_candidates: list[FlagCandidate]


class FinancialAnalystOutput(BaseModel):
    """What the pipeline stage actually returns, after grounding."""

    ticker: str
    summary: str
    flags: list[Flag]
    coverage_gaps: list[CoverageGap]
    dropped_candidates: list[str] = []
