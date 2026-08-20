"""Eval dataset for the Sector Analyst (Phase 4).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.sector_analyst
Passing bar (see .agents/plans/phase-4-sector-macro-valuation.md):
- SectorGroundingEvaluator's `is_grounded` at 100% across all cases — hard gate (this holds by
  construction, since run_sector_analyst never returns an ungrounded summary — see
  agents/sector.py). `fallback_triggered` at 100% False is the real quality signal: it means the
  model's own narrative was grounded on the first attempt, not that the runtime gate silently
  papered over bad output.
- ExpectedCoverageGapPresent passes on the thin-peer-set case.
- LLMJudge narrative-quality rubric passes on at least 3/4 (softest bar — never loosen the rubric
  to make a failure disappear, flag it instead).
"""

from dataclasses import dataclass

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import SECTOR_ANALYST_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import (
    extract_numbers,
    summary_is_grounded,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.sector_analyst import SectorAnalystOutput, SectorPeerData
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials
from agentic_fundamental_analyst.valuation import peer_multiples


def _peer(
    ticker: str, price: float, shares: float, revenue: float, net_income: float
) -> PeerFinancials:
    return PeerFinancials(
        ticker=ticker,
        price=price,
        shares_outstanding=shares,
        revenue=revenue,
        net_income=net_income,
        ebitda=None,
        total_debt=0.0,
        cash_and_equivalents=0.0,
    )


_SIC = "7370"
_SIC_DESC = "Services-Computer Programming, Data Processing, Etc."

# --- premium_to_peer_median: target's P/E ~30, peer medians ~15 ---
_PREMIUM_TARGET = _peer("PREM", price=300.0, shares=10.0, revenue=1000.0, net_income=100.0)
_PREMIUM_PEERS = [
    _peer("PEERA", price=140.0, shares=10.0, revenue=900.0, net_income=100.0),
    _peer("PEERB", price=160.0, shares=10.0, revenue=950.0, net_income=100.0),
    _peer("PEERC", price=150.0, shares=10.0, revenue=920.0, net_income=100.0),
]

# --- discount_to_peer_median: target's P/E ~8, peer medians ~15 ---
_DISCOUNT_TARGET = _peer("DISC", price=80.0, shares=10.0, revenue=1000.0, net_income=100.0)
_DISCOUNT_PEERS = _PREMIUM_PEERS

# --- at_peer_median_no_notable_signal: target sits right at peer medians ---
_ATMED_TARGET = _peer("ATMED", price=150.0, shares=10.0, revenue=930.0, net_income=100.0)
_ATMED_PEERS = _PREMIUM_PEERS

# --- thin_peer_set_coverage_gap: only 1 peer found ---
_THIN_TARGET = _peer("THIN", price=150.0, shares=10.0, revenue=1000.0, net_income=100.0)
_THIN_PEERS = [_peer("SOLE", price=140.0, shares=10.0, revenue=900.0, net_income=100.0)]


def _peer_data(
    ticker: str,
    target: PeerFinancials,
    peers: list[PeerFinancials],
    coverage_gaps: list[CoverageGap],
) -> SectorPeerData:
    return SectorPeerData(
        ticker=ticker,
        sic_code=_SIC,
        sic_description=_SIC_DESC,
        target=target,
        peers=peers,
        comps=peer_multiples(target, peers),
        coverage_gaps=coverage_gaps,
    )


_THIN_GAP = CoverageGap(
    field="peers", reason=f"insufficient peer data for SIC {_SIC}: found 1, needed >= 2"
)


def _known_numbers_from_case(peer_data: SectorPeerData) -> set[float]:
    """Reimplemented independently from agents/sector.py's own
    _known_numbers_from_sector, as a real cross-check rather than trusting
    the module under test — same idiom as
    evals/financial_statements.py's _known_numbers (see that module's own
    docstring note)."""
    known: set[float] = set()
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
    for gap in peer_data.coverage_gaps:
        known.update(extract_numbers(gap.reason))
    return known


@dataclass
class SectorGroundingEvaluator(Evaluator[SectorPeerData, SectorAnalystOutput, dict]):
    """Independently recomputes the known-number set from the case's own
    input and re-checks the output summary against it — doubles as a
    regression check on the agent's own grounding collector, not just on
    agent behavior. fallback_triggered (detected via the public
    coverage_gaps reason, not a private import) is the real quality signal —
    is_grounded holds by construction (run_sector_analyst never returns an
    ungrounded summary), so fallback_triggered=False on every case is what
    actually shows the model's prompt reliably produces grounded prose."""

    def evaluate(
        self, ctx: EvaluatorContext[SectorPeerData, SectorAnalystOutput, dict]
    ) -> dict[str, bool]:
        known = _known_numbers_from_case(ctx.inputs)
        return {
            "is_grounded": summary_is_grounded(ctx.output.summary, known),
            "fallback_triggered": any(
                g.reason == "numeric_grounding_check_failed" for g in ctx.output.coverage_gaps
            ),
        }


@dataclass
class ExpectedCoverageGapPresent(Evaluator[SectorPeerData, SectorAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[SectorPeerData, SectorAnalystOutput, dict]
    ) -> bool:
        expected_substring = (ctx.metadata or {}).get("expected_coverage_gap_substring")
        if expected_substring is None:
            return True
        return any(expected_substring in g.reason for g in ctx.output.coverage_gaps)


_SUMMARY_QUALITY_RUBRIC = (
    "The summary is a specific, numeric comparison of this company's own multiples to its real "
    "peer set's multiples/medians, not generic sector commentary that could describe any company "
    "sharing this SIC code. If the peer set has fewer than 2 peers, the summary explicitly "
    "qualifies that the comparison is low-confidence rather than presenting a 1-peer median as a "
    "solid benchmark. A summary describing the target as sitting near peer medians with no "
    "notable divergence is NOT a violation when that is genuinely what the numbers show."
)

dataset = Dataset(
    name="sector_analyst",
    cases=[
        Case(
            name="premium_to_peer_median",
            inputs=_peer_data("PREM", _PREMIUM_TARGET, _PREMIUM_PEERS, []),
        ),
        Case(
            name="discount_to_peer_median",
            inputs=_peer_data("DISC", _DISCOUNT_TARGET, _DISCOUNT_PEERS, []),
        ),
        Case(
            name="at_peer_median_no_notable_signal",
            inputs=_peer_data("ATMED", _ATMED_TARGET, _ATMED_PEERS, []),
        ),
        Case(
            name="thin_peer_set_coverage_gap",
            inputs=_peer_data("THIN", _THIN_TARGET, _THIN_PEERS, [_THIN_GAP]),
            metadata={"expected_coverage_gap_substring": "insufficient peer data"},
        ),
    ],
    evaluators=[
        SectorGroundingEvaluator(),
        ExpectedCoverageGapPresent(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=SECTOR_ANALYST_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.sector import run_sector_analyst

    report = dataset.evaluate_sync(run_sector_analyst)
    report.print(include_input=False, include_output=True, include_durations=True)
