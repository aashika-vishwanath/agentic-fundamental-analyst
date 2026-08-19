import json
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.fred import FredClient, FredError

GOLDEN = Path(__file__).parent.parent / "golden"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


@respx.mock
async def test_missing_value_sentinel_coerced_to_none(monkeypatch):
    monkeypatch.setenv("FRED_KEY", "fake-key-for-test")
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(200, json=_load("fred_dgs10_sample.json"))
    )

    bundle = await FredClient().observations("DGS10", start=date(2024, 1, 1))

    assert bundle.series_id == "DGS10"
    assert len(bundle.points) == 8
    holiday = next(p for p in bundle.points if p.obs_date == date(2024, 1, 1))
    assert holiday.value is None
    trading_day = next(p for p in bundle.points if p.obs_date == date(2024, 1, 2))
    assert trading_day.value == 3.95


async def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("FRED_KEY", raising=False)
    with pytest.raises(FredError):
        await FredClient().observations("DGS10")
