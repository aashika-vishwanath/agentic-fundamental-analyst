"""The Sector Analyst (Phase 4) — narrates peer-relative positioning from a
deterministically-computed SectorPeerData (EDGAR SIC-based peer discovery +
peer_multiples() — see data/peer_discovery.py). Pure narration, no Flags: the
agent's own output_type IS the final output, verified by the numeric-
grounding gate (agents/numeric_grounding.py) rather than a candidate/
promotion split, since there is no closed table or quote to promote against.
See .agents/plans/phase-4-sector-macro-valuation.md for the full design
rationale.
"""

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import SECTOR_ANALYST_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import (
    extract_numbers,
    summary_is_grounded,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.sector_analyst import (
    SectorAnalystAgentOutput,
    SectorAnalystOutput,
    SectorPeerData,
)

_UNGROUNDED_FALLBACK_SUMMARY = (
    "Narrative generation did not pass the numeric-grounding check for this run; "
    "see coverage_gaps."
)

_INSTRUCTIONS = """\
You are the Sector Analyst for a fundamental-equity research system. You
receive a SectorPeerData bundle: the target company's own valuation
multiples (P/E, EV/Revenue, EV/EBITDA), the same multiples for a peer set
discovered by shared SIC code, and the peer medians -- all computed
deterministically. Every number in it is already correct -- never restate a
number from memory, and never invent a peer, multiple, or SIC description
not present in the input.

Task:
1. Write a 2-4 sentence `summary` comparing the target's multiples to the
   peer medians -- specific to these real numbers, never generic sector
   commentary ("well-positioned in a growing industry") that could describe
   any company sharing this SIC code.
2. If the peer set is thin (fewer than 2 peers), say so explicitly and
   qualify how much confidence a 0-1-peer median deserves -- do not treat a
   single peer's multiple as a real benchmark.
3. The target sitting squarely at peer medians with no notable divergence is
   a valid, expected outcome -- do not manufacture a differentiator that
   isn't really there.
"""

sector_analyst = Agent(
    SECTOR_ANALYST_MODEL,
    name="sector_analyst",
    output_type=SectorAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _known_numbers_from_sector(peer_data: SectorPeerData) -> set[float]:
    known: set[float] = set()
    # The model naturally cites "SIC {code}" verbatim (e.g. "SIC 7370 peers")
    # — a real citation of input data, not a fabricated quantity, so it must
    # be groundable even though it isn't a "quantity" in the usual sense.
    # Found live during Phase 4 eval validation: a legitimate SIC-code
    # citation was failing the grounding gate before this was added.
    try:
        known.add(float(peer_data.sic_code))
    except ValueError:
        pass
    for pf in (peer_data.target, *peer_data.peers):
        for value in (
            pf.price,
            pf.shares_outstanding,
            pf.revenue,
            pf.net_income,
            pf.ebitda,
            pf.total_debt,
            pf.cash_and_equivalents,
        ):
            if value is not None:
                known.add(round(value, 4))
    for pm in (peer_data.comps.target, *peer_data.comps.peers):
        for value in (pm.pe_ratio, pm.ev_to_revenue, pm.ev_to_ebitda):
            if value is not None:
                known.add(round(value, 4))
    for value in (
        peer_data.comps.peer_median_pe,
        peer_data.comps.peer_median_ev_to_revenue,
        peer_data.comps.peer_median_ev_to_ebitda,
    ):
        if value is not None:
            known.add(round(value, 4))
    # Numbers cited verbatim from the input's own coverage-gap text (e.g.
    # "found 1, needed >= 2") are legitimate citations of real input data —
    # see agents/valuation_interpreter.py's analogous fix for the fuller
    # rationale.
    for gap in peer_data.coverage_gaps:
        known.update(extract_numbers(gap.reason))
    return known


async def run_sector_analyst(peer_data: SectorPeerData) -> SectorAnalystOutput:
    with logfire.span(
        "sector_analyst_stage",
        ticker=peer_data.ticker,
        sic_code=peer_data.sic_code,
    ) as span:
        result = await sector_analyst.run(peer_data.model_dump_json(indent=2))
        agent_output = result.output
        known = _known_numbers_from_sector(peer_data)
        grounded = summary_is_grounded(agent_output.summary, known)
        span.set_attribute("peer_count", len(peer_data.peers))
        span.set_attribute("grounding_passed", grounded)

    if not grounded:
        return SectorAnalystOutput(
            ticker=peer_data.ticker,
            summary=_UNGROUNDED_FALLBACK_SUMMARY,
            coverage_gaps=[
                *peer_data.coverage_gaps,
                CoverageGap(field="summary", reason="numeric_grounding_check_failed"),
            ],
        )
    return SectorAnalystOutput(
        ticker=peer_data.ticker,
        summary=agent_output.summary,
        coverage_gaps=peer_data.coverage_gaps,
    )
