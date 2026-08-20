from datetime import date
from typing import Literal

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class DCFScenario(BaseModel):
    label: Literal["bull", "base", "bear"]
    discount_rate: float
    terminal_growth: float
    present_value: float | None  # None when discount_rate <= terminal_growth (invalid)


class DCFResult(BaseModel):
    cash_flows: list[float]
    scenarios: list[DCFScenario]


class PeerFinancials(BaseModel):
    ticker: str
    price: float
    shares_outstanding: float
    revenue: float | None
    net_income: float | None
    ebitda: float | None
    total_debt: float | None
    cash_and_equivalents: float | None


class PeerMultiples(BaseModel):
    ticker: str
    pe_ratio: float | None
    ev_to_revenue: float | None
    ev_to_ebitda: float | None


class PeerCompsResult(BaseModel):
    target: PeerMultiples
    peers: list[PeerMultiples]
    peer_median_pe: float | None
    peer_median_ev_to_revenue: float | None
    peer_median_ev_to_ebitda: float | None


class ValuationAssumptions(BaseModel):
    """Phase 4 — every field here must be surfaced in the memo as a
    disclosed assumption, never stated as fact (investment-memo-writing
    skill §1 Section 6)."""

    risk_free_rate: float  # latest FRED DGS10 observation, as a decimal (e.g. 0.042)
    risk_free_rate_as_of: date  # that observation's date — for the Appendix citation
    equity_risk_premium: float  # fixed assumption constant, not fetched — see valuation.py
    discount_rate: float  # risk_free_rate + equity_risk_premium
    terminal_growth: float  # fixed assumption constant


class ValuationResult(BaseModel):
    ticker: str
    assumptions: ValuationAssumptions
    dcf: DCFResult | None  # None if fewer than 2 usable trailing FCF periods
    comps: PeerCompsResult | None  # None if zero usable peers found
    coverage_gaps: list[CoverageGap]
