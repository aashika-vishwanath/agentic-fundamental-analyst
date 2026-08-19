"""Tiingo client — primary daily OHLCV price source (free tier: 1,000
req/day, 50/hour, documented REST API, free key required).
"""

import os
from datetime import date, timedelta

import httpx

import agentic_fundamental_analyst.config  # noqa: F401 — loads .env for TIINGO_KEY
from agentic_fundamental_analyst.contracts.prices import PriceBar, PriceHistory
from agentic_fundamental_analyst.data.cache import cached

_BASE_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"


class TiingoError(Exception):
    pass


def _api_key() -> str:
    key = os.environ.get("TIINGO_KEY")
    if not key:
        raise TiingoError("TIINGO_KEY environment variable is not set")
    return key


@cached("tiingo_prices", timedelta(days=1))
async def _fetch_prices(ticker: str, start_date: str | None, end_date: str | None) -> list[dict]:
    params = {"token": _api_key(), "format": "json"}
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_BASE_URL.format(ticker=ticker.lower()), params=params)
        if resp.status_code == 404:
            raise TiingoError(f"Tiingo has no data for ticker {ticker!r}")
        if resp.status_code == 429:
            raise TiingoError("Tiingo daily/hourly request quota exceeded")
        resp.raise_for_status()
        return resp.json()


def _bar_from_row(row: dict) -> PriceBar:
    return PriceBar(
        bar_date=date.fromisoformat(row["date"][:10]),
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=int(row["volume"]),
        adj_close=row["adjClose"],
    )


class TiingoClient:
    async def daily_prices(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> list[PriceBar]:
        rows = await _fetch_prices(
            ticker,
            start.isoformat() if start else None,
            end.isoformat() if end else None,
        )
        return [_bar_from_row(row) for row in rows]


class PriceClient:
    """Unified price source. Tiingo only for now — Stooq's CSV backfill
    fallback is blocked (see stooq.py docstring); PRD §5 designates it as a
    fallback, not the critical path, so this is not a Phase 0 blocker.
    """

    def __init__(self) -> None:
        self._tiingo = TiingoClient()

    async def daily_prices(
        self, ticker: str, start: date | None = None, end: date | None = None
    ) -> PriceHistory:
        bars = await self._tiingo.daily_prices(ticker, start, end)
        return PriceHistory(ticker=ticker.upper(), source="tiingo", bars=bars)
