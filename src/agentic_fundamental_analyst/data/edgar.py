"""SEC EDGAR client: submissions, XBRL company concepts, full-text search.

No API key required, but every request needs a descriptive User-Agent and
must stay under ~10 req/s (throttled here to ~8 req/s with exponential
backoff on 403/429), per .agents/references/free-data-sources.md §1.
"""

import asyncio
import os
import time
from datetime import date, timedelta

import httpx

from agentic_fundamental_analyst.contracts.filings import EightKItemSource, FilingSections
from agentic_fundamental_analyst.contracts.financials import (
    CoverageGap,
    FinancialStatementBundle,
    FiscalPeriod,
)
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.transcripts import TranscriptInput
from agentic_fundamental_analyst.data.cache import cached
from agentic_fundamental_analyst.data.excluded_sic import classify_sic
from agentic_fundamental_analyst.data.filing_sections import (
    extract_8k_item_bodies,
    extract_10k_sections,
    extract_plain_text,
    looks_like_transcript_body,
)
from agentic_fundamental_analyst.data.tag_aliases import TAG_ALIASES

_DEFAULT_USER_AGENT = "agentic-fundamental-analyst aashikavishwanath@gmail.com"
_MIN_REQUEST_INTERVAL = 1.0 / 8.0  # ~8 req/s, under SEC's 10 req/s limit
_MAX_RETRIES = 5

# A 10-K's own original filing is always within ~120 days of its period_end
# (the SEC deadline is 60-90 days depending on filer size; 120 gives slack).
# If the earliest-filed occurrence of a (period_end, "10-K") key arrived later
# than that, it wasn't that period's own filing — it's a prior-year
# comparative column inside a *later* 10-K, which still carries that later
# filing's own `fy` stamp (e.g. a FY2015 10-K's FY2013/FY2014 comparative
# income-statement columns are tagged fy=2015 in the XBRL data, not fy=2013/
# fy=2014). See get_financial_statement_bundle's post-loop correction below.
_COMPARATIVE_COLUMN_FILING_LAG_DAYS = 120

# Many 10-Ks (pre-~2020, when SEC required it) include a "Selected Quarterly
# Financial Data" footnote — quarterly revenue/net income for the past two
# years, disclosed *inside* the 10-K document. When XBRL-tagged, each
# quarter's duration fact still carries form="10-K" (it's literally in that
# document) even though its duration is ~90 days, not a full fiscal year.
# Left unfiltered, each such quarter becomes its own spurious "annual" period
# once form == "10-K" is used as a proxy for "this is the whole fiscal year"
# (as compute_trend_bundle does). Confirmed present in real AAPL data (66
# quarterly net_income points, 6 quarterly revenue points, all form="10-K");
# confirmed absent for GOOGL, which is why it wasn't caught by GOOGL-only
# validation. Only duration-type facts are affected — instant (balance-sheet)
# concepts have no duration to mis-measure.
_ANNUAL_DURATION_DAYS_RANGE = (350, 380)

# XBRL "instant" facts (balance-sheet items, reported as of one date, no
# start/end duration) vs. "duration" facts (income/cash-flow items, reported
# over a start-end span) — duration facts need the YTD-vs-quarter filter,
# instant facts don't.
_INSTANT_CONCEPTS = {
    "accounts_receivable",
    "inventory",
    "total_assets",
    "current_assets",
    "ppe_gross",
    "total_debt",
}

# get_filing_sections()'s 8-K fetching only ever looked at the single latest
# 8-K (Phase 0/1). Checklist items tied to specific, rare 8-K item types
# (auditor change 4.01, officer turnover 5.02, restatement 4.02 — Phase 2)
# would almost never surface if the single latest 8-K on file happens to be
# something routine (an earnings release, a Reg FD disclosure) instead —
# which it usually is. Bounded to 12 so cost/latency stays predictable; each
# fetch is disk-cached 7 days, so this is a one-time-per-ticker-per-week cost,
# not a per-run one.
_RECENT_8K_LOOKBACK = 12

# A transcript is never embedded as 8-K item body text — it's furnished as a
# *separate exhibit document* within the same accession (confirmed live
# against a real transcript-bearing 8-K, CIK 1130713, accession
# 0001130713-15-000020: the primary document only says "a transcript is
# furnished as Exhibit 99.1"; the real transcript text is a sibling file,
# ex991q115earningscalltrans.htm). Discovering exhibit filenames requires the
# per-accession file index, not the submissions.json filings list (which only
# records each filing's primaryDocument).
_ACCESSION_NON_EXHIBIT_SUFFIXES = ("-index.html", "-index-headers.html", ".txt")


class EdgarError(Exception):
    pass


def _user_agent() -> str:
    return os.environ.get("EDGAR_USER_AGENT", _DEFAULT_USER_AGENT)


_last_request_at: float = 0.0
_throttle_lock = asyncio.Lock()


async def _throttle() -> None:
    global _last_request_at
    async with _throttle_lock:
        elapsed = time.monotonic() - _last_request_at
        if elapsed < _MIN_REQUEST_INTERVAL:
            await asyncio.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        _last_request_at = time.monotonic()


async def _get_json(url: str, params: dict | None = None) -> dict | None:
    """GET a JSON endpoint. Returns None on 404 (concept/company not found,
    not an error). Retries with exponential backoff on 403/429.
    """
    backoff = 1.0
    async with httpx.AsyncClient(headers={"User-Agent": _user_agent()}, timeout=30.0) as client:
        for _ in range(_MAX_RETRIES):
            await _throttle()
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return None
            if resp.status_code in (403, 429):
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json()
    raise EdgarError(f"exceeded {_MAX_RETRIES} retries fetching {url}")


async def _get_text(url: str) -> str | None:
    """GET an HTML/text document (a filing primary document, not a JSON
    API). Same 404/throttle/backoff handling as _get_json."""
    backoff = 1.0
    async with httpx.AsyncClient(headers={"User-Agent": _user_agent()}, timeout=30.0) as client:
        for _ in range(_MAX_RETRIES):
            await _throttle()
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            if resp.status_code in (403, 429):
                await asyncio.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.text
    raise EdgarError(f"exceeded {_MAX_RETRIES} retries fetching {url}")


@cached("edgar_filing_html", timedelta(days=7))
async def _fetch_filing_html(url: str) -> str | None:
    return await _get_text(url)


@cached("edgar_company_tickers", timedelta(days=7))
async def _fetch_company_tickers() -> dict:
    data = await _get_json("https://www.sec.gov/files/company_tickers.json")
    if data is None:
        raise EdgarError("company_tickers.json returned 404")
    return data


@cached("edgar_submissions", timedelta(days=7))
async def _fetch_submissions(cik10: str) -> dict | None:
    return await _get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")


@cached("edgar_company_concept", timedelta(days=7))
async def _fetch_company_concept(cik10: str, taxonomy: str, tag: str) -> dict | None:
    return await _get_json(
        f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/{taxonomy}/{tag}.json"
    )


@cached("edgar_full_text_search", timedelta(days=7))
async def _fetch_full_text_search(query: str, forms: tuple[str, ...]) -> dict:
    params: dict = {"q": query}
    if forms:
        params["forms"] = ",".join(forms)
    data = await _get_json("https://efts.sec.gov/LATEST/search-index", params=params)
    return data or {}


@cached("edgar_accession_index", timedelta(days=7))
async def _fetch_accession_index(cik10: str, accession_number: str) -> dict | None:
    """Per-accession file index (every document filed under one accession,
    including exhibits) — submissions.json's filings.recent only records
    each filing's primaryDocument, not its exhibits, so this is the only way
    to discover a transcript exhibit's filename."""
    cik_no_zeros = cik10.lstrip("0") or "0"
    accession_no_dashes = accession_number.replace("-", "")
    return await _get_json(
        f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeros}/{accession_no_dashes}/index.json"
    )


def _zero_pad_cik(cik: str) -> str:
    return cik.strip().lstrip("0").zfill(10) if cik.strip() else cik


class EdgarClient:
    """Thin async wrapper over SEC EDGAR's submissions, XBRL, and full-text
    search endpoints. Every method returns a typed model or a plain dict
    (for raw submissions metadata not yet promoted to a contract) — never
    passes a dict across a pipeline stage boundary.
    """

    async def ticker_to_cik(self, ticker: str) -> str | None:
        """Resolve a ticker to a 10-digit zero-padded CIK, or None if unknown."""
        data = await _fetch_company_tickers()
        ticker_upper = ticker.upper()
        for entry in data.values():
            if entry["ticker"].upper() == ticker_upper:
                return str(entry["cik_str"]).zfill(10)
        return None

    async def submissions(self, cik10: str) -> dict | None:
        """Raw submissions payload (filer name, SIC, recent filings list)."""
        return await _fetch_submissions(cik10)

    async def company_concept(
        self, cik10: str, tag: str, taxonomy: str = "us-gaap"
    ) -> dict | None:
        """Raw companyconcept payload for one exact tag, or None if the filer
        never used that tag (caller should try the next alias)."""
        return await _fetch_company_concept(cik10, taxonomy, tag)

    async def resolve_concept(self, cik10: str, concept: str) -> tuple[str, dict] | None:
        """Try every tag alias for `concept` (see tag_aliases.py) in order;
        return (tag_used, raw_payload) for the first that resolves, else None.
        """
        for tag in TAG_ALIASES.get(concept, []):
            payload = await self.company_concept(cik10, tag)
            if payload is not None and payload.get("units", {}).get("USD"):
                return tag, payload
        return None

    async def full_text_search(self, query: str, forms: list[str] | None = None) -> dict:
        return await _fetch_full_text_search(query, tuple(forms or ()))

    async def latest_filing(self, cik10: str, form: str) -> dict | None:
        """Most recent filing of `form` (e.g. "10-K", "8-K") from the
        submissions payload's `filings.recent` arrays, or None if the filer
        has none on record. Raw dict (accessionNumber, primaryDocument,
        filingDate, reportDate, items) — not yet promoted to FilingMetadata
        since only the fields get_filing_sections needs are used here.
        """
        recent = await self._recent_filings(cik10, form, limit=1)
        return recent[0] if recent else None

    async def _recent_filings(self, cik10: str, form: str, limit: int) -> list[dict]:
        """Up to `limit` most recent filings of `form`, most recent first —
        generalizes latest_filing() for the lookback scans below. Raw dicts
        (accessionNumber, primaryDocument, filingDate, reportDate, items)."""
        submissions = await self.submissions(cik10)
        if submissions is None:
            return []
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        report_dates = recent.get("reportDate", [])
        matches: list[dict] = []
        for i, filed_form in enumerate(forms):
            if filed_form != form:
                continue
            report_date_raw = report_dates[i] if i < len(report_dates) else ""
            matches.append(
                {
                    "accessionNumber": recent["accessionNumber"][i],
                    "primaryDocument": recent["primaryDocument"][i],
                    "filingDate": recent["filingDate"][i],
                    "reportDate": report_date_raw or None,
                    "items": recent.get("items", [""] * len(forms))[i],
                }
            )
            if len(matches) >= limit:
                break
        return matches

    async def _accession_exhibit_documents(
        self, cik10: str, accession_number: str, primary_document: str
    ) -> list[str]:
        """.htm/.html documents filed under `accession_number`, excluding the
        primary document and the index/header/full-submission-text files —
        i.e. the exhibits. Empty list (never an error) if the index can't be
        fetched or has none."""
        index = await _fetch_accession_index(cik10, accession_number)
        if index is None:
            return []
        items = index.get("directory", {}).get("item", [])
        names = [item.get("name", "") for item in items]
        return [
            name
            for name in names
            if name
            and name != primary_document
            and name.lower().endswith((".htm", ".html"))
            and not name.lower().endswith(_ACCESSION_NON_EXHIBIT_SUFFIXES)
        ]

    def filing_document_url(self, cik10: str, accession_number: str, primary_document: str) -> str:
        cik_no_zeros = cik10.lstrip("0") or "0"
        accession_no_dashes = accession_number.replace("-", "")
        return (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{cik_no_zeros}/{accession_no_dashes}/{primary_document}"
        )

    async def get_filing_sections(self, cik10: str) -> FilingSections:
        """Latest 10-K's Item 1/1A/7/9A, plus item bodies merged across a
        bounded scan of the _RECENT_8K_LOOKBACK most recent 8-Ks (not just
        the single latest — see the module-level comment on
        _RECENT_8K_LOOKBACK for why). 8-K exhibit coverage in general is
        opportunistic (PRD §7: only ~20-30% of filers use it); absence is a
        CoverageGap, never an empty section pretending to be found.
        """
        coverage_gaps: list[CoverageGap] = []

        ten_k = await self.latest_filing(cik10, "10-K")
        if ten_k is None:
            coverage_gaps.append(CoverageGap(field="item_1_business", reason="no_10k_on_file"))
            coverage_gaps.append(
                CoverageGap(field="item_1a_risk_factors", reason="no_10k_on_file")
            )
            coverage_gaps.append(CoverageGap(field="item_7_mdna", reason="no_10k_on_file"))
            coverage_gaps.append(CoverageGap(field="item_9a_controls", reason="no_10k_on_file"))
            accession_number = ""
            filed_date: date | None = None
            period_of_report: date | None = None
            sections: dict[str, str | None] = {
                "item_1_business": None,
                "item_1a_risk_factors": None,
                "item_7_mdna": None,
                "item_9a_controls": None,
            }
        else:
            accession_number = ten_k["accessionNumber"]
            filed_date = date.fromisoformat(ten_k["filingDate"])
            report_date_raw = ten_k["reportDate"]
            period_of_report = date.fromisoformat(report_date_raw) if report_date_raw else None
            url = self.filing_document_url(cik10, accession_number, ten_k["primaryDocument"])
            html = await _fetch_filing_html(url)
            if html is None:
                for field in (
                    "item_1_business",
                    "item_1a_risk_factors",
                    "item_7_mdna",
                    "item_9a_controls",
                ):
                    coverage_gaps.append(
                        CoverageGap(field=field, reason="10k_primary_document_fetch_failed")
                    )
                sections = {
                    "item_1_business": None,
                    "item_1a_risk_factors": None,
                    "item_7_mdna": None,
                    "item_9a_controls": None,
                }
            else:
                sections = extract_10k_sections(html)
                for field, value in sections.items():
                    if value is None:
                        coverage_gaps.append(
                            CoverageGap(field=field, reason="item_header_not_found_in_10k_body")
                        )

        eightk_item_bodies: dict[str, str] = {}
        eightk_item_sources: dict[str, EightKItemSource] = {}
        recent_8ks = await self._recent_filings(cik10, "8-K", _RECENT_8K_LOOKBACK)
        if not recent_8ks:
            coverage_gaps.append(CoverageGap(field="eightk_item_bodies", reason="no_8k_on_file"))
        else:
            any_fetch_failed = False
            for filing in recent_8ks:
                url = self.filing_document_url(
                    cik10, filing["accessionNumber"], filing["primaryDocument"]
                )
                html = await _fetch_filing_html(url)
                if html is None:
                    any_fetch_failed = True
                    continue
                bodies = extract_8k_item_bodies(html)
                # Most-recent-wins: recent_8ks is already most-recent-first,
                # so the first filing to claim an item number keeps it.
                for item_number, body in bodies.items():
                    if item_number not in eightk_item_bodies:
                        eightk_item_bodies[item_number] = body
                        eightk_item_sources[item_number] = EightKItemSource(
                            accession_number=filing["accessionNumber"],
                            filed_date=date.fromisoformat(filing["filingDate"]),
                        )
            if any_fetch_failed and not eightk_item_bodies:
                coverage_gaps.append(
                    CoverageGap(
                        field="eightk_item_bodies", reason="8k_primary_document_fetch_failed"
                    )
                )
            elif not eightk_item_bodies:
                coverage_gaps.append(
                    CoverageGap(
                        field="eightk_item_bodies", reason="no_item_headers_found_in_8k_body"
                    )
                )

        return FilingSections(
            accession_number=accession_number,
            filed_date=filed_date,
            period_of_report=period_of_report,
            item_1_business=sections["item_1_business"],
            item_1a_risk_factors=sections["item_1a_risk_factors"],
            item_7_mdna=sections["item_7_mdna"],
            item_9a_controls=sections["item_9a_controls"],
            eightk_item_bodies=eightk_item_bodies,
            eightk_item_sources=eightk_item_sources,
            coverage_gaps=coverage_gaps,
        )

    async def get_transcript_input(self, cik10: str) -> TranscriptInput | None:
        """Scans the _RECENT_8K_LOOKBACK most recent 8-Ks for one exhibit
        document whose text matches looks_like_transcript_body(). Returns
        the first (most recent) match, or None if the window is exhausted —
        an explicit, expected outcome per PRD §7's ~20-30% coverage
        estimate, never an error and never a fabricated fallback.
        """
        recent_8ks = await self._recent_filings(cik10, "8-K", _RECENT_8K_LOOKBACK)
        for filing in recent_8ks:
            exhibit_names = await self._accession_exhibit_documents(
                cik10, filing["accessionNumber"], filing["primaryDocument"]
            )
            for exhibit_name in exhibit_names:
                url = self.filing_document_url(cik10, filing["accessionNumber"], exhibit_name)
                html = await _fetch_filing_html(url)
                if html is None:
                    continue
                text = extract_plain_text(html)
                if looks_like_transcript_body(text):
                    return TranscriptInput(
                        accession_number=filing["accessionNumber"],
                        filed_date=date.fromisoformat(filing["filingDate"]),
                        exhibit_document=exhibit_name,
                        text=text,
                    )
        return None

    async def get_ticker_intake(self, ticker: str) -> TickerIntakeResult:
        """Resolve ticker -> CIK -> SIC code, and check it against the
        excluded-sector list (PRD §7) before any other data is fetched.
        """
        cik10 = await self.ticker_to_cik(ticker)
        if cik10 is None:
            raise EdgarError(f"no CIK found for ticker {ticker!r}")
        submissions = await self.submissions(cik10)
        if submissions is None:
            raise EdgarError(f"no submissions found for CIK {cik10}")
        sic_code = str(submissions.get("sic", ""))
        sic_description = str(submissions.get("sicDescription", ""))
        excluded = classify_sic(sic_code)
        if excluded is not None:
            exclusion_reason, canonical_description = excluded
            return TickerIntakeResult(
                ticker=ticker.upper(),
                cik=cik10,
                sic_code=sic_code,
                sic_description=sic_description or canonical_description,
                in_scope=False,
                exclusion_reason=exclusion_reason,
            )
        return TickerIntakeResult(
            ticker=ticker.upper(),
            cik=cik10,
            sic_code=sic_code,
            sic_description=sic_description,
            in_scope=True,
            exclusion_reason=None,
        )

    async def get_financial_statement_bundle(
        self, ticker: str, cik10: str
    ) -> FinancialStatementBundle:
        """Build a multi-period FinancialStatementBundle by resolving every
        concept in TAG_ALIASES via `resolve_concept`, keyed by (period_end,
        form) — not the XBRL `fy`/`fp` stamp, which is unreliable for dedup
        (see inline comment below). A concept that resolves for zero periods,
        or a filer that never used any alias for it, produces a CoverageGap
        instead of a false 0.0 (PRD principle #4).
        """
        coverage_gaps: list[CoverageGap] = []
        periods_by_key: dict[tuple[date, str], dict] = {}
        first_filed_by_key: dict[tuple[date, str], date] = {}
        # (period_end, form, concept) -> duration (days) of the value
        # currently stored in that row/field, so a later, longer-duration
        # (e.g. YTD-cumulative) fact never overwrites an already-found
        # discrete-quarter one.
        best_duration_by_field: dict[tuple[date, str, str], int] = {}

        for concept in TAG_ALIASES:
            resolved = await self.resolve_concept(cik10, concept)
            if resolved is None:
                coverage_gaps.append(
                    CoverageGap(field=concept, reason="no_xbrl_tag_alias_resolved")
                )
                continue
            _tag, payload = resolved
            for point in payload.get("units", {}).get("USD", []):
                form = point.get("form", "")
                if form not in ("10-K", "10-Q"):
                    continue
                end_raw = point.get("end")
                if end_raw is None:
                    continue
                end = date.fromisoformat(end_raw)

                # Duration facts (revenue, net income, capex, D&A, op cash
                # flow) are often tagged at more than one duration for the
                # same end date — a discrete quarter AND a YTD-cumulative
                # figure (cash-flow-statement lines, in particular, are
                # frequently tagged YTD-only in 10-Qs, with no discrete-
                # quarter figure ever reported). Prefer the shortest
                # duration available per field so a true discrete-quarter
                # figure always wins when it exists, and YTD is used only
                # when it's the sole figure the filer ever tagged — never
                # silently dropped to a coverage gap when real data exists.
                duration_days: int | None = None
                if concept not in _INSTANT_CONCEPTS:
                    start_raw = point.get("start")
                    if start_raw is None:
                        continue
                    duration_days = (end - date.fromisoformat(start_raw)).days
                    if duration_days <= 0:
                        continue
                    if form == "10-K" and not (
                        _ANNUAL_DURATION_DAYS_RANGE[0]
                        <= duration_days
                        <= _ANNUAL_DURATION_DAYS_RANGE[1]
                    ):
                        # A short-duration fact inside a 10-K is quarterly
                        # footnote data, not the annual figure — skip it
                        # rather than let it masquerade as a fiscal year.
                        continue

                fy = point.get("fy")
                fp = point.get("fp")
                if fy is None or fp is None:
                    continue

                # The same physical period is re-reported (as a prior-year
                # comparative) in every later filing, each stamped with that
                # later filing's own `fy` — e.g. Q2 2025 shows up again inside
                # the Q2 2026 10-Q with fy=2026. Identity is (period_end,
                # form), never the fy/fp stamp; the earliest-filed occurrence
                # is the authoritative source for fy/fp labeling.
                key = (end, form)
                filed_raw = point.get("filed")
                filed = date.fromisoformat(filed_raw) if filed_raw else date.max
                row = periods_by_key.setdefault(
                    key,
                    {
                        "fiscal_year": int(fy),
                        "fiscal_period": str(fp),
                        "form": form,
                        "period_end": end,
                    },
                )
                if filed <= first_filed_by_key.get(key, date.max):
                    first_filed_by_key[key] = filed
                    row["fiscal_year"] = int(fy)
                    row["fiscal_period"] = str(fp)

                if concept in _INSTANT_CONCEPTS:
                    row[concept] = point.get("val")
                else:
                    field_key = (end, form, concept)
                    prior_duration = best_duration_by_field.get(field_key)
                    assert duration_days is not None
                    if prior_duration is None or duration_days < prior_duration:
                        best_duration_by_field[field_key] = duration_days
                        row[concept] = point.get("val")

        # Correct fiscal_year/fiscal_period for 10-K periods whose only
        # observed occurrence is a later filing's comparative column (see
        # _COMPARATIVE_COLUMN_FILING_LAG_DAYS above) — period_end.year is a
        # safe, reliable fiscal-year label for an annual (form == "10-K",
        # fiscal_period == "FY") period; not extended to 10-Qs, where
        # non-calendar fiscal-year filers make that inference unsafe.
        for key, row in periods_by_key.items():
            end, form = key
            filed = first_filed_by_key.get(key)
            if (
                form == "10-K"
                and filed is not None
                and filed != date.max
                and (filed - end).days > _COMPARATIVE_COLUMN_FILING_LAG_DAYS
            ):
                row["fiscal_year"] = end.year
                row["fiscal_period"] = "FY"

        periods = [
            FiscalPeriod(
                fiscal_year=p["fiscal_year"],
                fiscal_period=p["fiscal_period"],
                form=p["form"],
                period_end=p["period_end"],
                revenue=p.get("revenue"),
                net_income=p.get("net_income"),
                capex=p.get("capex"),
                depreciation_amortization=p.get("depreciation_amortization"),
                accounts_receivable=p.get("accounts_receivable"),
                inventory=p.get("inventory"),
                total_assets=p.get("total_assets"),
                operating_cash_flow=p.get("operating_cash_flow"),
                cost_of_revenue=p.get("cost_of_revenue"),
                sga_expense=p.get("sga_expense"),
                current_assets=p.get("current_assets"),
                ppe_gross=p.get("ppe_gross"),
                total_debt=p.get("total_debt"),
            )
            for p in periods_by_key.values()
        ]
        periods.sort(key=lambda p: p.period_end, reverse=True)

        return FinancialStatementBundle(
            ticker=ticker.upper(),
            cik=cik10,
            periods=periods,
            coverage_gaps=coverage_gaps,
        )
