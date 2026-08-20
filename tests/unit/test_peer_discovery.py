import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.contracts.prices import PriceBar, PriceHistory
from agentic_fundamental_analyst.contracts.valuation import PeerFinancials
from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.edgar import EdgarClient
from agentic_fundamental_analyst.data.peer_discovery import (
    PeerDiscoveryError,
    discover_sector_peers,
)
from agentic_fundamental_analyst.data.tiingo import TiingoError

GOLDEN = Path(__file__).parent.parent / "golden"

# Synthetic (not a captured real response) — reuses the two real CIKs from
# company_tickers_sample.json (AAPL, GOOGL) plus one unmatched CIK, to test
# the cross-referencing/filtering logic in isolation from the real feed's
# actual shape (already covered by test_sic_lookup.py against the real
# golden fixture).
_SIC_FEED_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><content type="text/xml">
    <company-info><cik>0000320193</cik></company-info>
  </content></entry>
  <entry><content type="text/xml">
    <company-info><cik>0001652044</cik></company-info>
  </content></entry>
  <entry><content type="text/xml">
    <company-info><cik>0009999999</cik></company-info>
  </content></entry>
</feed>"""


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


@respx.mock
async def test_peers_by_sic_excludes_target_and_unmatched_ciks():
    respx.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar\?.*").mock(
        return_value=httpx.Response(200, text=_SIC_FEED_XML)
    )
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load("company_tickers_sample.json"))
    )

    # Exclude GOOGL (the "target"); AAPL should survive, the unmatched CIK
    # (0009999999, not in company_tickers_sample.json) should be dropped.
    pairs = await EdgarClient().peers_by_sic("7370", exclude_cik="0001652044", limit=100)

    assert pairs == [("0000320193", "AAPL")]


@respx.mock
async def test_peers_by_sic_fetches_full_feed_page_regardless_of_small_limit():
    # Real bug caught during Phase 4 live validation: `limit` must cap only
    # the *returned* pair count, not the SIC feed's own page size — most raw
    # feed entries in registration order have no active ticker, so fetching
    # only `limit`-many raw candidates when limit is small (e.g. 15) can
    # legitimately return zero usable peers even when the true peer set is
    # large. Assert the feed request itself always asks for the full
    # _SIC_FEED_PAGE_SIZE page, independent of `limit`.
    route = respx.get(url__regex=r"https://www\.sec\.gov/cgi-bin/browse-edgar\?.*").mock(
        return_value=httpx.Response(200, text=_SIC_FEED_XML)
    )
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load("company_tickers_sample.json"))
    )

    pairs = await EdgarClient().peers_by_sic("7370", exclude_cik="0001652044", limit=1)

    assert pairs == [("0000320193", "AAPL")]
    assert route.called
    requested_url = route.calls.last.request.url
    assert requested_url.params["count"] == "100"


@respx.mock
async def test_build_peer_financials_assembles_from_resolved_concepts():
    cik10 = "0000320193"
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/CommonStockSharesOutstanding.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "units": {
                    "shares": [
                        {"end": "2025-09-30", "val": 15000000000},
                        {"end": "2026-06-30", "val": 15200000000},
                    ]
                }
            },
        )
    )
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/Revenues.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "units": {
                    "USD": [
                        {"end": "2025-12-31", "start": "2025-01-01", "val": 400e9, "form": "10-K"},
                        {"end": "2026-03-31", "start": "2026-01-01", "val": 90e9, "form": "10-Q"},
                    ]
                }
            },
        )
    )
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/NetIncomeLoss.json"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "units": {
                    "USD": [
                        {"end": "2025-12-31", "start": "2025-01-01", "val": 100e9, "form": "10-K"}
                    ]
                }
            },
        )
    )
    # total_debt and cash_and_equivalents: no alias resolves (all 404)
    respx.get(
        url__regex=rf"https://data\.sec\.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/"
        r"(DebtLongtermAndShorttermCombinedAmount|LongTermDebtNoncurrent|LongTermDebt|"
        r"CashAndCashEquivalentsAtCarryingValue|"
        r"CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents)\.json"
    ).mock(return_value=httpx.Response(404))

    peer = await EdgarClient().build_peer_financials("AAPL", cik10, price=200.0)

    assert peer is not None
    assert peer.ticker == "AAPL"
    assert peer.price == 200.0
    assert peer.shares_outstanding == 15200000000.0
    assert peer.revenue == 400e9
    assert peer.net_income == 100e9
    assert peer.total_debt is None
    assert peer.cash_and_equivalents is None
    assert peer.ebitda is None


@respx.mock
async def test_build_peer_financials_returns_none_when_shares_outstanding_unresolved():
    cik10 = "0000320193"
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/us-gaap/CommonStockSharesOutstanding.json"
    ).mock(return_value=httpx.Response(404))

    peer = await EdgarClient().build_peer_financials("AAPL", cik10, price=200.0)

    assert peer is None


def _peer_financials(ticker: str) -> PeerFinancials:
    return PeerFinancials(
        ticker=ticker,
        price=100.0,
        shares_outstanding=10.0,
        revenue=500.0,
        net_income=50.0,
        ebitda=None,
        total_debt=100.0,
        cash_and_equivalents=50.0,
    )


class _FakeEdgar:
    """Duck-typed stand-in for discover_sector_peers' orchestration logic —
    isolates it from EdgarClient's real HTTP/parsing, which is already
    covered by the tests above."""

    def __init__(
        self,
        target: PeerFinancials,
        peer_pairs: list[tuple[str, str]],
        resolvable_peer_tickers: set[str],
    ):
        self._target = target
        self._peer_pairs = peer_pairs
        self._resolvable = resolvable_peer_tickers

    async def build_peer_financials(self, ticker: str, cik10: str, price: float):
        if ticker == self._target.ticker:
            return self._target
        return _peer_financials(ticker) if ticker in self._resolvable else None

    async def peers_by_sic(self, sic_code: str, exclude_cik: str, limit: int):
        return self._peer_pairs[:limit]


class _FakePriceClient:
    """Every candidate has a resolvable price — build_peer_financials'
    resolvability (via _FakeEdgar) is what actually filters candidates in
    these tests, not price resolution."""

    async def daily_prices(self, ticker: str, start=None, end=None):
        return PriceHistory(
            ticker=ticker,
            source="tiingo",
            bars=[
                PriceBar(
                    bar_date=date.today(),
                    open=1.0,
                    high=1.0,
                    low=1.0,
                    close=1.0,
                    volume=1,
                    adj_close=1.0,
                )
            ],
        )


class _NoPricePriceClient:
    async def daily_prices(self, ticker: str, start=None, end=None):
        raise TiingoError(f"no data for {ticker}")


async def test_discover_sector_peers_stops_once_target_peer_count_reached():
    target = _peer_financials("TARGET")
    pairs = [(f"000000000{i}", f"PEER{i}") for i in range(8)]  # 8 candidates offered
    edgar = _FakeEdgar(target, pairs, resolvable_peer_tickers={p[1] for p in pairs})

    result = await discover_sector_peers(
        "TARGET", "0000000000", "7370", "Services-Computer Programming", target_price=100.0,
        edgar=edgar, price_client=_FakePriceClient(),
    )

    assert len(result.peers) == 5  # _TARGET_PEER_COUNT, not all 8 offered
    assert result.coverage_gaps == []


async def test_discover_sector_peers_flags_insufficient_peer_coverage_gap():
    target = _peer_financials("TARGET")
    pairs = [("0000000001", "PEER1"), ("0000000002", "PEER2")]
    # Only PEER1 resolves; PEER2 doesn't (e.g. no shares_outstanding tag)
    edgar = _FakeEdgar(target, pairs, resolvable_peer_tickers={"PEER1"})

    result = await discover_sector_peers(
        "TARGET", "0000000000", "7370", "Services-Computer Programming", target_price=100.0,
        edgar=edgar, price_client=_FakePriceClient(),
    )

    assert len(result.peers) == 1
    assert len(result.coverage_gaps) == 1
    assert "insufficient peer data" in result.coverage_gaps[0].reason


async def test_discover_sector_peers_excludes_candidate_with_unresolvable_price():
    target = _peer_financials("TARGET")
    pairs = [("0000000001", "PEER1")]
    edgar = _FakeEdgar(target, pairs, resolvable_peer_tickers={"PEER1"})

    result = await discover_sector_peers(
        "TARGET", "0000000000", "7370", "Services-Computer Programming", target_price=100.0,
        edgar=edgar, price_client=_NoPricePriceClient(),
    )

    assert result.peers == []
    assert "insufficient peer data" in result.coverage_gaps[0].reason


async def test_discover_sector_peers_raises_when_target_financials_unresolvable():
    edgar = _FakeEdgar(_peer_financials("OTHER"), [], resolvable_peer_tickers=set())

    with pytest.raises(PeerDiscoveryError):
        await discover_sector_peers(
            "TARGET", "0000000000", "7370", "Services-Computer Programming", target_price=100.0,
            edgar=edgar, price_client=_FakePriceClient(),
        )
