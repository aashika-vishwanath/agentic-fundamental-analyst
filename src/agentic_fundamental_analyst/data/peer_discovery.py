"""Peer-discovery orchestration (Phase 4): SIC lookup -> per-candidate price +
financials fetch -> peer_multiples(). Kept separate from edgar.py because it's
cross-cutting (EdgarClient + PriceClient + valuation.py's pure math), not pure
EDGAR access. Computed once here and consumed by both the Sector Analyst
(peer/segment narrative) and the Valuation Interpreter (valuation cross-check)
— see the Phase 4 plan's Problem/Solution for why peer discovery isn't
duplicated per-agent.
"""

import asyncio
from datetime import date, timedelta
from typing import Protocol

import logfire

# Import order matters: config loads .env (LOGFIRE_TOKEN) before observability
# configures Logfire. Every agent module already does this at import time;
# this module needs it too since it emits its own span (peer_discovery_stage)
# and, unlike every prior deterministic stage in this codebase, is a
# plausible standalone entry point (data/peer_discovery.py has no agent
# dependency) — without this import, calling discover_sector_peers() before
# any agent module happens to be imported silently no-ops the span
# (LogfireNotConfiguredWarning) rather than recording it. Found live during
# Phase 4 post-implementation validation.
from agentic_fundamental_analyst import config, observability  # noqa: F401,E402
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.prices import PriceHistory
from agentic_fundamental_analyst.contracts.sector_analyst import SectorPeerData
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials
from agentic_fundamental_analyst.data.edgar import EdgarClient
from agentic_fundamental_analyst.data.tiingo import PriceClient, TiingoError
from agentic_fundamental_analyst.valuation import peer_multiples


class _PeerFinancialsSource(Protocol):
    """Structural interface EdgarClient satisfies — Protocol (not the
    concrete class) so tests can pass a lightweight duck-typed fake without
    a nominal-typing mismatch (see test_peer_discovery.py's _FakeEdgar)."""

    async def build_peer_financials(
        self, ticker: str, cik10: str, price: float
    ) -> PeerFinancials | None: ...

    async def peers_by_sic(
        self, sic_code: str, exclude_cik: str, limit: int
    ) -> list[tuple[str, str]]: ...


class _PriceSource(Protocol):
    async def daily_prices(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> PriceHistory: ...

# Try candidates in feed order until this many usable peers are assembled...
_TARGET_PEER_COUNT = 5
# ...or this many candidates have been attempted, whichever comes first —
# bounds worst-case latency (SIC lookup can return dozens of candidates, many
# of them shells/SPACs with no usable financials — confirmed live, see the
# Phase 4 plan's Research Findings).
_MAX_PEER_CANDIDATES_TRIED = 15
# Fetched concurrently per batch (asyncio.gather) to keep wall-clock latency
# down despite EDGAR's shared ~8 req/s throttle.
_PEER_FETCH_BATCH_SIZE = 5
# Below this many real peers, comps medians are statistically thin — still
# returned (peer_multiples handles 0-1 peers fine via _median_ignoring_none),
# but flagged as an explicit coverage gap rather than presented as a solid
# benchmark.
_MIN_PEER_COUNT_FOR_COMPS = 2
# Small window — only the most recent close is needed, not full history.
_PRICE_LOOKBACK_DAYS = 10


class PeerDiscoveryError(Exception):
    """Raised only when the target's own peer financials can't be built —
    a company with real market data and a real 10-K filing essentially
    always has a resolvable price and shares_outstanding, so this signals a
    genuine system problem, not a routine coverage gap (contrast with a
    candidate *peer* being unresolvable, which is expected/routine and
    handled by simply excluding that candidate)."""


async def _latest_price(price_client: _PriceSource, ticker: str) -> float | None:
    try:
        history = await price_client.daily_prices(
            ticker, start=date.today() - timedelta(days=_PRICE_LOOKBACK_DAYS)
        )
    except TiingoError:
        return None
    if not history.bars:
        return None
    return max(history.bars, key=lambda b: b.bar_date).close


async def _build_candidate(
    edgar: _PeerFinancialsSource, price_client: _PriceSource, cik10: str, ticker: str
) -> PeerFinancials | None:
    price = await _latest_price(price_client, ticker)
    if price is None:
        return None
    return await edgar.build_peer_financials(ticker, cik10, price)


async def discover_sector_peers(
    ticker: str,
    cik: str,
    sic_code: str,
    sic_description: str,
    target_price: float,
    edgar: _PeerFinancialsSource | None = None,
    price_client: _PriceSource | None = None,
) -> SectorPeerData:
    edgar_client = edgar or EdgarClient()
    prices = price_client or PriceClient()

    with logfire.span(
        "peer_discovery_stage", ticker=ticker, sic_code=sic_code
    ) as span:
        target_financials = await edgar_client.build_peer_financials(ticker, cik, target_price)
        if target_financials is None:
            raise PeerDiscoveryError(
                f"could not resolve shares_outstanding for {ticker} (CIK {cik}) — "
                "cannot build peer comps for the target itself"
            )

        candidates = await edgar_client.peers_by_sic(
            sic_code, exclude_cik=cik, limit=_MAX_PEER_CANDIDATES_TRIED
        )

        peers: list[PeerFinancials] = []
        candidates_scanned = 0
        for batch_start in range(0, len(candidates), _PEER_FETCH_BATCH_SIZE):
            if len(peers) >= _TARGET_PEER_COUNT:
                break
            batch = candidates[batch_start : batch_start + _PEER_FETCH_BATCH_SIZE]
            candidates_scanned += len(batch)
            results = await asyncio.gather(
                *(
                    _build_candidate(edgar_client, prices, peer_cik10, peer_ticker)
                    for peer_cik10, peer_ticker in batch
                )
            )
            for result in results:
                if result is not None:
                    peers.append(result)
                if len(peers) >= _TARGET_PEER_COUNT:
                    break

        coverage_gaps: list[CoverageGap] = []
        if len(peers) < _MIN_PEER_COUNT_FOR_COMPS:
            coverage_gaps.append(
                CoverageGap(
                    field="peers",
                    reason=(
                        f"insufficient peer data for SIC {sic_code}: found {len(peers)}, "
                        f"needed >= {_MIN_PEER_COUNT_FOR_COMPS}"
                    ),
                )
            )

        span.set_attribute("candidates_scanned", candidates_scanned)
        span.set_attribute("peers_found", len(peers))

    comps = peer_multiples(target_financials, peers)
    return SectorPeerData(
        ticker=ticker.upper(),
        sic_code=sic_code,
        sic_description=sic_description,
        target=target_financials,
        peers=peers,
        comps=comps,
        coverage_gaps=coverage_gaps,
    )
