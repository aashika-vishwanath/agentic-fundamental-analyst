import json
from pathlib import Path

import httpx
import pytest
import respx

from agentic_fundamental_analyst.data.cache import clear_cache
from agentic_fundamental_analyst.data.edgar import EdgarClient
from agentic_fundamental_analyst.data.tag_aliases import TAG_ALIASES

GOLDEN = Path(__file__).parent.parent / "golden"
CIK10 = "0001652044"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text())


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


@respx.mock
async def test_bundle_dedups_comparative_and_prefers_discrete_quarter_over_ytd():
    respx.get(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK10}/us-gaap/Revenues.json"
    ).mock(return_value=httpx.Response(200, json=_load("googl_revenue_concept.json")))
    respx.get(
        url__regex=rf"https://data\.sec\.gov/api/xbrl/companyconcept/CIK{CIK10}/us-gaap/.*\.json"
    ).mock(return_value=httpx.Response(404))

    bundle = await EdgarClient().get_financial_statement_bundle("GOOGL", CIK10)

    # revenue resolved; every other concept resolved to nothing -> CoverageGap
    gap_fields = {g.field for g in bundle.coverage_gaps}
    assert gap_fields == set(TAG_ALIASES) - {"revenue"}

    by_end = {p.period_end.isoformat(): p for p in bundle.periods}

    # No duplicate row for the Q2 2025 comparative re-reported in the Q2 2026 10-Q
    q2_2025_rows = [p for p in bundle.periods if p.period_end.isoformat() == "2025-06-30"]
    assert len(q2_2025_rows) == 1
    # Discrete-quarter revenue (96.4B), not the YTD 6-month figure (186.7B)
    assert q2_2025_rows[0].revenue == 96428000000.0
    # fy/fp label comes from the earliest (originating) filing, not the later comparative
    assert q2_2025_rows[0].fiscal_year == 2025

    # Q3 2025 also prefers discrete quarter (102.3B) over YTD 9-month (289.0B)
    assert by_end["2025-09-30"].revenue == 102346000000.0

    # FY 2025 (10-K, annual) is unaffected by the quarter/YTD distinction
    assert by_end["2025-12-31"].revenue == 402836000000.0
    assert by_end["2025-12-31"].form == "10-K"

    # No two rows share the same (period_end, form)
    keys = [(p.period_end, p.form) for p in bundle.periods]
    assert len(keys) == len(set(keys))


@respx.mock
async def test_bundle_all_concepts_missing_yields_all_coverage_gaps_no_periods():
    respx.get(
        url__regex=rf"https://data\.sec\.gov/api/xbrl/companyconcept/CIK{CIK10}/us-gaap/.*\.json"
    ).mock(return_value=httpx.Response(404))

    bundle = await EdgarClient().get_financial_statement_bundle("GOOGL", CIK10)

    assert bundle.periods == []
    assert len(bundle.coverage_gaps) == len(TAG_ALIASES)
    assert all(g.reason == "no_xbrl_tag_alias_resolved" for g in bundle.coverage_gaps)
