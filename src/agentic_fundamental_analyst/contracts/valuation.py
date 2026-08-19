from typing import Literal

from pydantic import BaseModel


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
