import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.tiingo import TiingoClient, TiingoError

GOLDEN = Path(__file__).parent.parent / "golden"


def _load(name: str) -> list:
    return json.loads((GOLDEN / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


@respx.mock
async def test_daily_prices_parses_bars(monkeypatch):
    monkeypatch.setenv("TIINGO_KEY", "fake-key-for-test")
    respx.get("https://api.tiingo.com/tiingo/daily/aapl/prices").mock(
        return_value=httpx.Response(200, json=_load("tiingo_aapl_sample.json"))
    )

    bars = await TiingoClient().daily_prices("AAPL", start=date(2024, 1, 1), end=date(2024, 1, 10))

    assert len(bars) == 7
    assert bars[0].bar_date == date(2024, 1, 2)
    assert bars[0].close == 185.64
    assert bars[0].adj_close == 183.4133636527
    assert bars[0].volume == 82488674


async def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("TIINGO_KEY", raising=False)
    with pytest.raises(TiingoError):
        await TiingoClient().daily_prices("AAPL")


@respx.mock
async def test_quota_exhaustion_raises_typed_error(monkeypatch):
    monkeypatch.setenv("TIINGO_KEY", "fake-key-for-test")
    respx.get("https://api.tiingo.com/tiingo/daily/aapl/prices").mock(
        return_value=httpx.Response(429)
    )
    with pytest.raises(TiingoError):
        await TiingoClient().daily_prices("AAPL")
