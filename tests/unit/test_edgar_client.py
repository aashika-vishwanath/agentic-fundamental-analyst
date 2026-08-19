import json
from datetime import date
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


MBUU_CIK10 = "0001590976"
OSTK_CIK10 = "0001130713"


def _mock_empty_index(accession_dashes: str, cik_no_zeros: str) -> None:
    respx.get(
        f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_dashes}/index.json"
    ).mock(return_value=httpx.Response(200, json={"directory": {"item": []}}))


@respx.mock
async def test_get_filing_sections_merges_item_bodies_across_lookback_scan():
    """MBUU's real, trimmed submissions.json has 2 real 8-Ks in the lookback
    window: the single latest (routine 2.02 earnings release) and an older
    one (5.02, officer appointment/departure) 4 positions back. Neither is
    the single 'latest' 8-K test coverage exercised before this phase — this
    proves an item from a non-latest 8-K in the window still surfaces."""
    respx.get(f"https://data.sec.gov/submissions/CIK{MBUU_CIK10}.json").mock(
        return_value=httpx.Response(200, json=_load("mbuu_submissions_sample.json"))
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1590976/000159097625000080/mbuu-20250630.htm"
    ).mock(return_value=httpx.Response(200, text=(GOLDEN / "mbuu_10k_sample.html").read_text()))
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1590976/000159097626000015/mbuu-20260507.htm"
    ).mock(
        return_value=httpx.Response(
            200, text=(GOLDEN / "mbuu_8k_latest_202_sample.html").read_text()
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1590976/000159097625000117/mbuu-20251112.htm"
    ).mock(
        return_value=httpx.Response(
            200, text=(GOLDEN / "mbuu_8k_item502_sample.html").read_text()
        )
    )

    sections = await EdgarClient().get_filing_sections(MBUU_CIK10)

    assert sections.period_of_report == date(2025, 6, 30)
    assert sections.filed_date == date(2025, 8, 28)
    # From the latest (2.02/9.01) 8-K:
    assert "2.02" in sections.eightk_item_bodies
    assert sections.eightk_item_sources["2.02"].accession_number == "0001590976-26-000015"
    # From the older-but-in-window (5.02/7.01/9.01) 8-K — proves the scan
    # isn't limited to the single latest filing:
    assert "5.02" in sections.eightk_item_bodies
    assert sections.eightk_item_sources["5.02"].accession_number == "0001590976-25-000117"
    assert sections.eightk_item_sources["5.02"].filed_date == date(2025, 11, 13)
    # "9.01" appears in both 8-Ks -- most-recent-wins (the latest filing's).
    assert sections.eightk_item_sources["9.01"].accession_number == "0001590976-26-000015"


@respx.mock
async def test_get_transcript_input_returns_none_when_no_exhibit_matches():
    """Same MBUU fixture set as above -- neither 8-K has a transcript
    exhibit, so this must return None, not raise or guess."""
    respx.get(f"https://data.sec.gov/submissions/CIK{MBUU_CIK10}.json").mock(
        return_value=httpx.Response(200, json=_load("mbuu_submissions_sample.json"))
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1590976/000159097626000015/mbuu-20260507.htm"
    ).mock(
        return_value=httpx.Response(
            200, text=(GOLDEN / "mbuu_8k_latest_202_sample.html").read_text()
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1590976/000159097625000117/mbuu-20251112.htm"
    ).mock(
        return_value=httpx.Response(
            200, text=(GOLDEN / "mbuu_8k_item502_sample.html").read_text()
        )
    )
    _mock_empty_index("000159097626000015", "1590976")
    _mock_empty_index("000159097625000117", "1590976")

    result = await EdgarClient().get_transcript_input(MBUU_CIK10)

    assert result is None


@respx.mock
async def test_get_transcript_input_finds_real_transcript_exhibit():
    """A real transcript-bearing 8-K (CIK 1130713, accession
    0001130713-15-000020): the primary document alone has no transcript-
    shaped text (it only announces one was furnished); the exhibit
    discovered via the accession's file index does."""
    respx.get(f"https://data.sec.gov/submissions/CIK{OSTK_CIK10}.json").mock(
        return_value=httpx.Response(200, json=_load("overstock_submissions_sample.json"))
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1130713/000113071315000020/index.json"
    ).mock(
        return_value=httpx.Response(
            200, json=_load("overstock_accession_index_sample.json")
        )
    )
    respx.get(
        "https://www.sec.gov/Archives/edgar/data/1130713/000113071315000020/"
        "ex991q115earningscalltrans.htm"
    ).mock(
        return_value=httpx.Response(
            200, text=(GOLDEN / "overstock_8k_transcript_sample.html").read_text()
        )
    )

    result = await EdgarClient().get_transcript_input(OSTK_CIK10)

    assert result is not None
    assert result.accession_number == "0001130713-15-000020"
    assert result.exhibit_document == "ex991q115earningscalltrans.htm"
    assert result.filed_date == date(2015, 5, 1)
    assert "Operator" in result.text
