from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst import valuation
from agentic_fundamental_analyst.agents.sector import run_sector_analyst, sector_analyst
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.sector_analyst import (
    SectorAnalystAgentOutput,
    SectorPeerData,
)
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials

TARGET = PeerFinancials(
    ticker="TEST",
    price=224.0,
    shares_outstanding=10.0,  # market cap 2,240, pe = 2240/100 = 22.4
    revenue=1000.0,
    net_income=100.0,
    ebitda=None,
    total_debt=0.0,
    cash_and_equivalents=0.0,
)

PEER = PeerFinancials(
    ticker="PEER",
    price=181.0,
    shares_outstanding=10.0,  # market cap 1,810, pe = 1810/100 = 18.1
    revenue=900.0,
    net_income=100.0,
    ebitda=None,
    total_debt=0.0,
    cash_and_equivalents=0.0,
)

COMPS = valuation.peer_multiples(TARGET, [PEER])

PEER_DATA = SectorPeerData(
    ticker="TEST",
    sic_code="7370",
    sic_description="Services-Computer Programming, Data Processing, Etc.",
    target=TARGET,
    peers=[PEER],
    comps=COMPS,
    coverage_gaps=[],
)


def test_agent_default_test_model_produces_valid_output_type():
    with sector_analyst.override(model=TestModel()):
        result = sector_analyst.run_sync(PEER_DATA.model_dump_json())
    assert isinstance(result.output, SectorAnalystAgentOutput)


async def test_run_sector_analyst_keeps_grounded_summary():
    # 22.4 and 18.1 are the real computed P/E ratios in COMPS.
    scripted = {"summary": "The target's P/E of 22.4 sits above the peer median of 18.1."}
    with sector_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_sector_analyst(PEER_DATA)

    assert "22.4" in result.summary
    assert result.coverage_gaps == []


async def test_run_sector_analyst_falls_back_on_fabricated_number():
    # A number far outside the magnitude of anything in PEER_DATA (raw
    # fields, ratios, or any pairwise percent-diff/ratio derived from them)
    # — deliberately not just "different-looking" but far enough in
    # magnitude that the tolerance-scaled grounding check can't coincidentally
    # match it against an unrelated real number (see is_grounded's
    # magnitude-scaled tolerance).
    scripted = {"summary": "The target trades at an eye-watering P/E of 8675309.0."}
    with sector_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_sector_analyst(PEER_DATA)

    assert result.summary != "The target trades at an eye-watering P/E of 8675309.0."
    assert any(g.reason == "numeric_grounding_check_failed" for g in result.coverage_gaps)


async def test_run_sector_analyst_grounds_verbatim_sic_code_citation():
    # The model naturally cites "SIC 7370" verbatim — a real citation of
    # input data, not a fabricated quantity. Found live during Phase 4 eval
    # validation (see agents/sector.py's _known_numbers_from_sector).
    scripted = {"summary": "Among SIC 7370 peers, the target trades near the median."}
    with sector_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_sector_analyst(PEER_DATA)

    assert result.summary == "Among SIC 7370 peers, the target trades near the median."
    assert result.coverage_gaps == []


async def test_run_sector_analyst_passthrough_coverage_gaps_on_success():
    peer_data_with_gap = PEER_DATA.model_copy(
        update={
            "coverage_gaps": [
                CoverageGap(
                    field="peers",
                    reason="insufficient peer data for SIC 7370: found 1, needed >= 2",
                )
            ]
        }
    )
    scripted = {"summary": "Only one peer available; treat this comp with low confidence."}
    with sector_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_sector_analyst(peer_data_with_gap)

    assert len(result.coverage_gaps) == 1
    assert "insufficient peer data" in result.coverage_gaps[0].reason
