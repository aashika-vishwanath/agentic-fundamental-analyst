from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.valuation import PeerCompsResult, PeerFinancials


class SectorPeerData(BaseModel):
    ticker: str
    sic_code: str
    sic_description: str
    target: PeerFinancials
    peers: list[PeerFinancials]  # may be empty — see coverage_gaps
    comps: PeerCompsResult  # computed even from an empty/short peer list (medians -> None)
    coverage_gaps: list[CoverageGap]


class SectorAnalystAgentOutput(BaseModel):
    """The agent's own output_type — narrower than the final stage output.
    Only `summary` is asked of the model; `ticker`/`coverage_gaps` on
    SectorAnalystOutput below are always assembled from SectorPeerData by
    code, never trusted from the model (same 'don't ask the model for
    metadata it shouldn't own' idiom as Phases 1-2's candidate/promotion
    split, applied here even without a candidate/grounding-drop step)."""

    summary: str


class SectorAnalystOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
