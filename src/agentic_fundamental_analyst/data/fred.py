"""FRED (Federal Reserve Economic Data) client — macro series observations.

Requires a free API key (env var FRED_KEY) — confirmed live during Phase 0
execution that a keyless request returns HTTP 400 "Variable api_key is not
set", correcting free-data-sources.md's earlier "works keyless at 30 req/min"
note. With a key: 120 req/min.
"""

import os
from datetime import date, timedelta

import httpx

import agentic_fundamental_analyst.config  # noqa: F401 — loads .env for FRED_KEY
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.data.cache import cached

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredError(Exception):
    pass


def _api_key() -> str:
    key = os.environ.get("FRED_KEY")
    if not key:
        raise FredError("FRED_KEY environment variable is not set")
    return key


@cached("fred_observations", timedelta(days=1))
async def _fetch_observations(series_id: str, observation_start: str | None) -> dict:
    params = {
        "series_id": series_id,
        "api_key": _api_key(),
        "file_type": "json",
    }
    if observation_start:
        params["observation_start"] = observation_start
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_BASE_URL, params=params)
        resp.raise_for_status()
        return resp.json()


class FredClient:
    async def observations(
        self, series_id: str, start: date | None = None
    ) -> MacroSeriesBundle:
        observation_start = start.isoformat() if start else None
        data = await _fetch_observations(series_id, observation_start)
        points = [
            MacroSeriesPoint(
                obs_date=date.fromisoformat(obs["date"]),
                value=None if obs["value"] == "." else float(obs["value"]),
            )
            for obs in data.get("observations", [])
        ]
        return MacroSeriesBundle(series_id=series_id, points=points)
