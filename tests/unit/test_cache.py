from datetime import timedelta

import pytest

from agentic_fundamental_analyst.data.cache import cached, clear_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def test_cached_second_call_does_not_reinvoke_within_ttl():
    calls = []

    @cached("test_source", timedelta(days=1))
    async def fetch(x: int) -> int:
        calls.append(x)
        return x * 2

    assert await fetch(3) == 6
    assert await fetch(3) == 6
    assert calls == [3]


async def test_cache_key_includes_all_args_not_just_first():
    calls = []

    @cached("test_source_2", timedelta(days=1))
    async def fetch(ticker: str, start: str) -> str:
        calls.append((ticker, start))
        return f"{ticker}:{start}"

    await fetch("AAPL", "2024-01-01")
    await fetch("AAPL", "2024-06-01")
    assert calls == [("AAPL", "2024-01-01"), ("AAPL", "2024-06-01")]
