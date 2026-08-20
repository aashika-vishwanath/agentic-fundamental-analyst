from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle


class CompanyMacroProfile(BaseModel):
    """Deliberately small — built from fields Phases 0-1 already fetch
    (TickerIntakeResult + FinancialStatementBundle), no new fetching."""

    ticker: str
    sic_description: str
    latest_revenue: float | None
    latest_total_debt: float | None
    revenue_cagr: float | None  # over the annual periods available; None if <2 periods


class MacroAnalystInput(BaseModel):
    """Typed wrapper — the agent's input is two separate objects
    (list[MacroSeriesBundle] + CompanyMacroProfile per the PRD roster), and
    every inter-stage boundary must be one typed model, never a dict or two
    positional arguments concatenated ad hoc."""

    macro_bundles: list[MacroSeriesBundle]
    profile: CompanyMacroProfile


class MacroAnalystAgentOutput(BaseModel):
    """The agent's own output_type — see SectorAnalystAgentOutput's
    docstring for why this is narrower than the stage output."""

    summary: str


class MacroAnalystOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
