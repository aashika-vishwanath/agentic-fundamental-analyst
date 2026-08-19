import json
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.contracts.intake import ExcludedSector
from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.edgar import EdgarClient, EdgarError

GOLDEN = Path(__file__).parent.parent / "golden"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


def _mock_tickers_and_submissions(cik10: str, submissions_fixture: str):
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load("company_tickers_sample.json"))
    )
    respx.get(f"https://data.sec.gov/submissions/CIK{cik10}.json").mock(
        return_value=httpx.Response(200, json=_load(submissions_fixture))
    )


@respx.mock
async def test_bank_ticker_is_excluded():
    _mock_tickers_and_submissions("0000019617", "jpm_submissions.json")
    result = await EdgarClient().get_ticker_intake("JPM")
    assert result.in_scope is False
    assert result.exclusion_reason == ExcludedSector.BANK
    assert result.sic_code == "6021"


@respx.mock
async def test_reit_ticker_is_excluded():
    _mock_tickers_and_submissions("0000726728", "o_submissions.json")
    result = await EdgarClient().get_ticker_intake("O")
    assert result.in_scope is False
    assert result.exclusion_reason == ExcludedSector.REIT
    assert result.sic_code == "6798"


@respx.mock
async def test_insurer_ticker_is_excluded():
    _mock_tickers_and_submissions("0001099219", "met_submissions.json")
    result = await EdgarClient().get_ticker_intake("MET")
    assert result.in_scope is False
    assert result.exclusion_reason == ExcludedSector.INSURER
    assert result.sic_code == "6311"


@respx.mock
async def test_non_financial_ticker_is_in_scope():
    _mock_tickers_and_submissions("0001652044", "googl_submissions.json")
    result = await EdgarClient().get_ticker_intake("GOOGL")
    assert result.in_scope is True
    assert result.exclusion_reason is None
    assert result.sic_code == "7370"


@respx.mock
async def test_unknown_ticker_raises():
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, json=_load("company_tickers_sample.json"))
    )
    with pytest.raises(EdgarError):
        await EdgarClient().get_ticker_intake("NOTATICKER")
