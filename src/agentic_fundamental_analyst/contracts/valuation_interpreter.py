from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class ValuationInterpreterAgentOutput(BaseModel):
    """The agent's own output_type — see
    contracts/sector_analyst.py::SectorAnalystAgentOutput's docstring for
    why this is narrower than the stage output."""

    summary: str


class ValuationInterpreterOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
