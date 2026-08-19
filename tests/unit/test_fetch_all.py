import json
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.prices import PriceHistory
from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.fetch import TickerOutOfScope, fetch_all

GOLDEN = Path(__file__).parent.parent / "golden"
GOOGL_CIK10 = "0001652044"
JPM_CIK10 = "0000019617"


def _load_json(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


def _load_text(name: str) -> str:
    return (GOLDEN / name).read_text()


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


@respx.mock
async def test_excluded_ticker_short_circuits_before_any_other_fetch(monkeypatch):
    """respx's default assert_all_mocked=True means this test only passes
    if fetch_all truly stops after intake — any attempt to reach FRED,
    Tiingo, or an EDGAR concept/filing endpoint (none mocked here) would
    raise an httpx error, not TickerOutOfScope."""
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load_json("company_tickers_sample.json"))
    )
    respx.get(f"https://data.sec.gov/submissions/CIK{JPM_CIK10}.json").mock(
        return_value=httpx.Response(200, json=_load_json("jpm_submissions.json"))
    )

    with pytest.raises(TickerOutOfScope) as exc_info:
        await fetch_all("JPM")
    assert exc_info.value.intake.sic_code == "6021"


@respx.mock
async def test_in_scope_ticker_returns_fully_typed_bundle(monkeypatch):
    monkeypatch.setenv("FRED_KEY", "fake-key-for-test")
    monkeypatch.setenv("TIINGO_KEY", "fake-key-for-test")

    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load_json("company_tickers_sample.json"))
    )
    respx.get(f"https://data.sec.gov/submissions/CIK{GOOGL_CIK10}.json").mock(
        return_value=httpx.Response(200, json=_load_json("googl_submissions.json"))
    )
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{GOOGL_CIK10}/us-gaap/Revenues.json"
    ).mock(return_value=httpx.Response(200, json=_load_json("googl_revenue_concept.json")))
    respx.get(
        url__regex=rf"https://data\.sec\.gov/api/xbrl/companyconcept/CIK{GOOGL_CIK10}/us-gaap/.*\.json"
    ).mock(return_value=httpx.Response(404))
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm"
    ).mock(return_value=httpx.Response(200, text=_load_text("googl_10k_item1_1a_7.html")))
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1652044/000119312526342390/d171253d8k.htm"
    ).mock(return_value=httpx.Response(200, text=_load_text("googl_8k_sample.html")))
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_load_json("fred_dgs10_sample.json"))
    )
    respx.get(url__regex=r"https://api\.tiingo\.com/tiingo/daily/googl/prices").mock(
        return_value=httpx.Response(200, json=_load_json("tiingo_aapl_sample.json"))
    )

    financials, filings, macro, prices = await fetch_all("GOOGL")

    assert isinstance(financials, FinancialStatementBundle)
    assert isinstance(filings, FilingSections)
    assert all(isinstance(m, MacroSeriesBundle) for m in macro)
    assert isinstance(prices, PriceHistory)

    assert financials.ticker == "GOOGL"
    assert filings.item_1_business is not None
    assert len(macro) == 3
    assert len(prices.bars) > 0
