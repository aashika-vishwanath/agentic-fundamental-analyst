# Data Layer — Implementation Reference

Status: Phase 0 + Phase 2 + Phase 4 extensions complete. Covers `EdgarClient`/`FredClient`/
`PriceClient`, the cache layer, filing-section parsing, XBRL tag aliases, SIC exclusion,
`fetch_all()`, and Phase 4's SIC-based peer discovery — as actually built, not as researched. For
source API research (endpoints, rate limits, auth), see `free-data-sources.md`.

---

## Layout

```
src/agentic_fundamental_analyst/
  config.py             # loads .env once, at import time (FRED_KEY, TIINGO_KEY, EDGAR_USER_AGENT)
  contracts/
    financials.py        # CoverageGap, XBRLFact, FiscalPeriod, FinancialStatementBundle
    filings.py            # FilingMetadata, FilingSections
    macro.py               # MacroSeriesPoint, MacroSeriesBundle
    prices.py                # PriceBar, PriceHistory
    intake.py                 # ExcludedSector, TickerIntakeResult
    ratios.py                  # RatioResult (value: float|None, reason: str|None)
    valuation.py                # DCFScenario, DCFResult, PeerFinancials, PeerMultiples,
                                 # PeerCompsResult, ValuationAssumptions, ValuationResult (Phase 4)
  data/
    cache.py              # cached() decorator, diskcache-backed, keyed on (source, func, args, kwargs)
    excluded_sic.py         # bank/insurer/REIT SIC code -> ExcludedSector map
    tag_aliases.py            # per-concept us-gaap tag fallback lists (13 concepts) +
                               # PEER_ONLY_TAG_ALIASES (Phase 4, cash_and_equivalents)
    sic_lookup.py              # Phase 4: parse_sic_atom_feed() — pure XML parsing
    edgar.py                    # EdgarClient: submissions, XBRL concepts, filings, intake,
                                 # peers_by_sic/build_peer_financials (Phase 4)
    filing_sections.py            # pure HTML parsing: 10-K Item 1/1A/7, 8-K item bodies
    fred.py                        # FredClient
    tiingo.py                       # TiingoClient, PriceClient
    stooq.py                         # BLOCKED — see module docstring
    peer_discovery.py                 # Phase 4: discover_sector_peers() orchestration
    fetch.py                           # fetch_all(ticker) -> gated on TickerIntakeResult.in_scope
  ratios.py                # DSO, Sloan accruals, cash conversion, capex/D&A, Beneish (8 components), CCC
  valuation.py              # dcf() bull/base/bear, peer_multiples(), trailing_free_cash_flows(),
                             # build_valuation_assumptions() (Phase 4)
```

## Cache layer (`data/cache.py`)

`@cached(source, ttl)` wraps an async fetch function. Key = sha256 of
`(source, func_name, args, kwargs)` (all args, not just the ticker — two
different date ranges are different cache entries). Backed by `diskcache`
at `~/.cache/agentic-fundamental-analyst`, shared across processes/runs.
`clear_cache()` wipes it — call at the top of any test/script that must not
see stale entries from a prior live run.

## EDGAR client (`data/edgar.py`)

Keyless; requires `User-Agent: <app> <email>` (env var `EDGAR_USER_AGENT`,
defaults to a placeholder — override in `.env` for real use) and is
throttled to ~8 req/s (SEC's real limit is 10/s) with exponential backoff
on 403/429.

**`get_financial_statement_bundle(ticker, cik10)`** resolves all 13
`TAG_ALIASES` concepts via `companyconcept`, one call per alias tried in
order, and merges every filer's fact stream into `FiscalPeriod` rows. Four
non-obvious bugs found and fixed by testing against live data (all four are
now regression-tested in `tests/unit/test_edgar_client.py`; #3 and #4 were
found during Phase 1's live validation of the Financial Statements Analyst,
not Phase 0 itself — a case of PRD §9's annotation-to-fix flywheel firing one
phase earlier than usual):

1. **Dedup key is `(period_end, form)`, never the XBRL `fy`/`fp` stamp.**
   The same physical quarter is re-reported as a prior-year comparative in
   every later filing, each stamped with *that later filing's own* `fy` —
   e.g. Q2 2025 shows up again inside the Q2 2026 10-Q with `fy=2026`.
   Deduping by `(fy, fp, form)` silently created a duplicate, mislabeled
   row. `period_end` is ground truth; `fy`/`fp` are only used (from the
   earliest-`filed` occurrence) for display labeling.

2. **Duration facts (revenue, capex, D&A, operating cash flow) are often
   tagged at more than one duration for the same `end` date** — a discrete
   quarter *and* a YTD-cumulative figure. Cash-flow-statement lines in
   particular are frequently tagged **YTD-only** in 10-Qs (no discrete
   quarter ever exists). Fix: per `(period_end, form, concept)`, keep
   whichever candidate has the **shortest** duration — this picks the
   discrete quarter when one exists, and falls back to the real YTD figure
   (not a coverage gap) when that's the only thing the filer ever tagged.

3. **Bug #1's "earliest-filed occurrence is authoritative for fy/fp" fallback
   assumed the earliest filing to report a period is always that period's own
   original 10-K — false when that period's own filing isn't independently
   observed in the fetched concept history.** Then the *only* observation of
   that `period_end` is a later filing's prior-year comparative column, whose
   `fy` stamp reflects the later filing's own fiscal year, not the period it's
   describing. Confirmed live: GOOGL's 2013 and 2014 periods came back labeled
   `fiscal_year=2015`, inherited from the FY2015 10-K's comparative columns.
   Fix: `_COMPARATIVE_COLUMN_FILING_LAG_DAYS = 120` — for `form == "10-K"`, if
   the earliest-filed occurrence of a period arrived more than 120 days after
   `period_end` (too late to be that period's own filing), `fiscal_year` is
   derived from `period_end.year` instead of trusting the inherited `fy`
   stamp. Scoped to 10-Ks only (`fiscal_period` is reliably `"FY"` there) —
   not extended to 10-Qs, where non-calendar fiscal-year filers make
   `period_end.year` an unsafe proxy for the quarter's fiscal year label.

4. **Duration length was never validated for `form == "10-K"` facts, so a
   10-K's own embedded "Selected Quarterly Financial Data" footnote (SEC-
   required pre-~2020: quarterly revenue/net income disclosed inside the 10-K
   itself) silently produced spurious "annual" periods.** Each footnote
   quarter's duration fact still carries `form="10-K"` (it's literally in
   that document) despite a ~90-day duration. Confirmed live: 66 spurious
   `net_income` points and 6 spurious `revenue` points for AAPL, all
   `form="10-K"`; confirmed **absent** for GOOGL (why GOOGL-only validation
   didn't catch this the first time). This also silently corrupted the
   *correct* annual figure whenever a quarterly footnote's `end` date
   coincided with the fiscal year-end (bug #2's shortest-duration-wins
   tiebreak would prefer the ~90-day footnote fact over the true ~365-day
   annual one at that shared date) — not just an extra-periods problem. Fix:
   `_ANNUAL_DURATION_DAYS_RANGE = (350, 380)` — a duration-type fact tagged
   `form == "10-K"` is now rejected outright unless its duration falls in
   that range. Verified post-fix: AAPL returns exactly 19 clean annual
   periods (2007-2025), GOOGL exactly 13 (2013-2025), zero spurious or
   mislabeled periods in either.

`get_filing_sections(cik10)` parses the latest 10-K's Item 1/1A/7/9A and item
bodies merged from a **lookback scan of up to 12 recent 8-Ks** (Phase 2 — see
below), not just the single latest. Coverage gaps are per-field, never a
blanket failure.

## Phase 2: 8-K lookback scan and transcript-exhibit discovery (`data/edgar.py`)

**Why the single-latest-8-K design (Phase 0/1) had to change**: checklist
items tied to specific, rare 8-K item types (auditor change 4.01, officer
turnover 5.02, restatement 4.02) would almost never surface if the single
latest 8-K on file happens to be something routine (an earnings release,
Reg FD disclosure) instead — which it usually is.

**`_recent_filings(cik10, form, limit)`** generalizes the old `latest_filing()`
to return up to `limit` filings of a form, most-recent-first (now also
carrying `reportDate`, confirmed as the real SEC field name against a live
payload — `latest_filing()` never extracted it before). `get_filing_sections()`
scans `_RECENT_8K_LOOKBACK = 12` recent 8-Ks and merges their
`extract_8k_item_bodies()` results into the same `eightk_item_bodies: dict[str,
str]` shape as before (most-recent-wins per item number — confirmed live: two
different 8-Ks in the same scan can both carry `"9.01"`, and the newer one's
body wins). New `eightk_item_sources: dict[str, EightKItemSource]` records
which accession/filed_date each surviving item number actually came from —
needed so a filing-derived `Flag` can be given a real `fiscal_year` (see
`agents.md`'s Filings Analyst section). `FilingSections` also gained
`filed_date`/`period_of_report` (the 10-K's own) and `item_9a_controls`
(`extract_10k_sections()`'s boundary-detection already finds every item
header; Phase 0 just discarded everything except 1/1A/7 from its result dict —
Phase 2 kept one more key).

**A transcript is never embedded in 8-K item body text.** Discovered live
against a real transcript-bearing 8-K (CIK 1130713, accession
0001130713-15-000020): the primary document's own Item 2.02/9.01 text only
says "a transcript is furnished as Exhibit 99.1" — the real transcript is a
*separate document* (`ex991q115earningscalltrans.htm`) within the same
accession, invisible to `extract_8k_item_bodies()` entirely. This wasn't
anticipated by the Phase 2 plan (which assumed the transcript would show up
as an item body) and was corrected during execution.

**`get_transcript_input(cik10)`** fixes this: for each of the
`_RECENT_8K_LOOKBACK` recent 8-Ks, it fetches the accession's own file index
(a new cached endpoint, `.../{accession}/index.json` — lists every document
filed under that accession, including exhibits) via
`_accession_exhibit_documents()`, filters to `.htm`/`.html` files excluding
the primary document and the index/header/full-submission-text files, fetches
each candidate, and checks `filing_sections.looks_like_transcript_body()`
against its plain text (`extract_plain_text()` — generic HTML-to-text, for
documents with no `Item N.NN` structure to segment on). Returns the first
match or `None` after exhausting the window — an explicit, expected outcome
(PRD §7's ~20-30% coverage estimate), never an error.

**`looks_like_transcript_body()` heuristic** (`filing_sections.py`) — also
corrected from the Phase 2 plan's original design during execution, after
testing against the real transcript exhibit above. The plan assumed speaker
turns would look like `"Name: ..."`; the real transcript (a standard
vendor-formatted earnings-call transcript) instead puts the speaker's
name/role on its own line, with **zero** colon-prefixed speaker lines. What
*is* reliably present: the word "Operator" appears as its own standalone
line 8 times (a real ordinary 8-K item body has zero); a "question-and-answer"
section marker is also present. Final heuristic: `>= 2` standalone `"Operator"`
lines **and** a question-and-answer marker — both signals independently
confirmed live against the real fixture and against three unrelated real 8-K
item bodies (auditor-change, officer-departure, restatement — zero false
positives).

## Filing section parsing (`data/filing_sections.py`)

**The hard part, and the reason this isn't plain-text regex.** A naive
`r"Item\s+\d+[A-Za-z]?\."` regex over `soup.get_text()` matches the Table
of Contents, inline cross-references ("see Item 1A Risk Factors..."), *and*
the real section header — all three look identical as plain text.

Verified fix (tested against real Alphabet and Apple 10-Ks, which use
different HTML conventions):

- The **Table of Contents** always wraps `Item N.` in a hyperlink
  (`<a href="#...">`).
- The **real section header** is always bold (`font-weight:700`, or a
  `<b>`/`<strong>` tag) and is *not* inside a link.
- Alphabet's real headers happen to also be ALL CAPS in the extracted text
  (a first-pass heuristic that worked for Alphabet); Apple's are mixed-case
  with CSS-driven visual capitalization, so the ALL-CAPS heuristic silently
  found *nothing* for Apple. The bold+non-hyperlink check is what actually
  generalizes.

`_is_real_header()` walks up to 8 ancestors from each `Item N.`-prefixed
text node: any `<a>` ancestor → reject (ToC); any bold ancestor → accept.
A filer whose headers aren't bold-styled will show up as a `CoverageGap`
(`item_header_not_found_in_10k_body`), never a wrong or truncated section.

8-K item bodies use plain regex (`r"Item\s+(\d+\.\d+)\.?\s*"`) — no ToC to
collide with. The trailing period is **optional**: Alphabet's 8-Ks write
`Item 8.01.` (with period), Apple's write `Item 2.02` (without) — both seen
live, both handled.

## FRED client (`data/fred.py`)

`FRED_KEY` is **required**, not optional — a keyless request returns HTTP
400 `"Variable api_key is not set"` (confirmed live; corrects
`free-data-sources.md`'s original "works keyless at 30 req/min" note).
The `"."` missing-value sentinel is coerced to `None` in `observations()`.

## Price client (`data/tiingo.py`, `data/stooq.py`)

`PriceClient` wraps **Tiingo only**. `TIINGO_KEY` required.

**Stooq is blocked, not implemented.** As of Phase 0 (2026-08), Stooq's
CSV endpoint (`stooq.com/q/d/l/?s=...`) returns a JavaScript proof-of-work
challenge page instead of data, for any plain HTTP client — confirmed via
`curl` with a real browser User-Agent and via a markdown-conversion fetch
tool. This is a bot-detection change since `free-data-sources.md`'s
original research. Since Stooq is the backfill fallback, not primary
(PRD §5), this doesn't block Phase 0; `data/stooq.py` is a stub that
raises `NotImplementedError` with the full explanation. Revisit if a
headless-browser fetch path is ever added.

## SIC exclusion (`data/excluded_sic.py`)

Codes verified live against SEC EDGAR's own
`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=...`
during Phase 0, cross-checked against the canonical SIC manual (Major
Group 60 — Depository Institutions; Major Groups 63/64 — Insurance;
6798 — REITs). `classify_sic(sic_code)` returns
`(ExcludedSector, canonical_description) | None`.

## Ratios (`ratios.py`) — Beneish M-Score contract extension

`FiscalPeriod` (PRD §6's sketch) only supports 3 of 8 Beneish components
out of the box. Extended with 5 fields beyond the PRD's illustrative
sketch — `cost_of_revenue`, `sga_expense`, `current_assets`, `ppe_gross`,
`total_debt` — to support all 8. `total_debt`'s tag-alias list is a known
simplification (approximates as long-term debt when no combined
long+short tag exists; see `tag_aliases.py` comment).

`cash_conversion_cycle()` is a **permanent, documented coverage gap** —
`FiscalPeriod` has no `accounts_payable` field (not part of the approved
extension), so the DPO leg of DSO+DIO−DPO can never compute. Revisit if a
later phase needs it.

## Valuation (`valuation.py`)

`dcf(cash_flows, discount_rate, terminal_growth)` returns bull/base/bear
scenarios via ±100bps discount rate / ±50bps terminal growth around the
supplied base case. `present_value=None` (not a fabricated number) when
`discount_rate <= terminal_growth`.

`peer_multiples(target, peers)` computes P/E, EV/Revenue, EV/EBITDA per
company plus peer medians (`statistics.median`, `None`s excluded — a peer
missing one input never zeroes out or skews the median).

**Phase 4 additions**: `trailing_free_cash_flows(bundle)` — last N annual
(10-K) `operating_cash_flow - capex`, oldest first, mirroring
`ratios.py::compute_trend_bundle`'s exact annual-period filter; `None` if
fewer than 2 usable periods. This is deliberately *not* a growth-projection
model — the investment-memo-writing skill specifies a **trailing/LTM DCF**
("filed cash flows"), so the last N years' real filed FCF is fed straight
into the existing `dcf()` as if it were the next N years' projection, no
forecasting step needed. `build_valuation_assumptions(macro_bundles)` —
risk-free rate from the latest non-`None` `DGS10` FRED point (divided by
100 — FRED reports a percentage like `4.20`, not a decimal) plus a fixed,
disclosed `_EQUITY_RISK_PREMIUM = 0.055` / `_TERMINAL_GROWTH_ASSUMPTION =
0.025` (conventional round numbers, not derived from any source — no free
ERP data source exists); `None` (a full coverage gap) if `DGS10` is missing
or entirely `None`-valued.

## `fetch_all()` (`data/fetch.py`)

Gated on `TickerIntakeResult.in_scope` — raises `TickerOutOfScope` (not a
`Union` return, unlike the plan's original sketch; kept consistent with
this codebase's existing typed-exception pattern — `EdgarError`,
`FredError`, `TiingoError`) before any other fetch for an excluded ticker.
Returns `(TickerIntakeResult, FinancialStatementBundle, FilingSections,
list[MacroSeriesBundle], PriceHistory, TranscriptInput | None)` — a
**6-tuple as of Phase 4** (previously 5; `intake` is now returned instead of
discarded after the exclusion check, since Phase 4's Sector/Macro agents
need its `sic_code`/`sic_description` and it was already resolved
internally on every call). Macro is a list of bundles (one per FRED series
in `_MACRO_SERIES_IDS`), not a single bundle, since a memo needs several
series (10Y yield, Fed funds, 10Y-2Y spread).

## Phase 4: SIC-based peer discovery (`data/sic_lookup.py`, `data/edgar.py`, `data/peer_discovery.py`)

**`data/sic_lookup.py::parse_sic_atom_feed()`** parses SEC EDGAR's
`browse-edgar?action=getcompany&SIC=...&output=atom` feed. **Confirmed live
gotcha**: this feed's `<entry title="...">` and `<company-info name="...">`
attributes are literal `"ARRAY(0x...)"` strings — a PHP/Perl
array-to-string bug on SEC's own legacy CGI page, not usable for company
name or ticker under any circumstance. Only `<cik>` is reliable per entry;
ticker/name resolution happens separately via the already-cached
`company_tickers.json` reverse index (`EdgarClient.peers_by_sic`).

**`EdgarClient.peers_by_sic(sic_code, exclude_cik, limit)`** — a real bug,
caught only by live validation against GOOGL/SIC-7370 (not by unit tests):
the original implementation passed `limit` straight through as the SIC
feed's own `count` param, conflating "how many raw candidates to fetch"
with "how many usable pairs to return." Since most raw feed entries in
registration order have no active ticker (shells/SPACs/delisted filers —
confirmed live), a small `limit` (15) legitimately fetched a page where
**zero** of the 15 raw candidates had a ticker at all. Fixed:
`_SIC_FEED_PAGE_SIZE = 100` (the confirmed-working max page size) is always
used for the feed fetch, decoupled from `limit`, which only caps the
*returned*, ticker-matched pair count. See the Phase 4 plan's Execution
Deviations §5 for the full account, including a related, non-bug finding:
even with discovery working, a SIC-code-based peer set's *quality* is
genuinely mixed (a broad SIC code spans micro-caps and large-caps alike) —
both Sector Analyst and Valuation Interpreter correctly treat a
low-quality/negative-earnings-skewed median as low-confidence rather than
presenting it as a real signal, but this is a permanent limitation of pure
SIC matching, not something the page-size fix addresses.

**`EdgarClient.build_peer_financials(ticker, cik10, price)`** assembles a
`PeerFinancials` via `_latest_annual_concept_value()` (revenue/net_income:
latest 10-K annual value, same filter as `get_financial_statement_bundle`;
total_debt/cash_and_equivalents: latest instant value regardless of form)
and `latest_shares_outstanding()` (`us-gaap:CommonStockSharesOutstanding`
via `company_concept()` directly — **confirmed live against GOOGL that this
tag resolves to a single combined ~12B-share total despite Alphabet's
multiple share classes, no per-class dimensional handling needed**; see
`tests/golden/googl_shares_outstanding_concept.json`). Deliberately *not*
added to `TAG_ALIASES`/`FiscalPeriod` — a new `PEER_ONLY_TAG_ALIASES` dict
(`data/tag_aliases.py`) keeps `cash_and_equivalents` out of
`get_financial_statement_bundle()`'s wholesale iteration, which would
otherwise spuriously mark it as a `CoverageGap` on every company that
doesn't tag it (caught before shipping, not live). `ebitda` is always
`None` for peers — no reliable generic-peer EBITDA source exists;
`PeerMultiples.ev_to_ebitda` already degrades to `None` gracefully.
Returns `None` only when `price`/`shares_outstanding` can't be resolved
(both non-`Optional` `PeerFinancials` fields) — that candidate is excluded
from the peer set entirely, never included with a fabricated number.

**`data/peer_discovery.py::discover_sector_peers()`** — the orchestration
function tying the above together (SIC lookup → per-candidate price
[`PriceClient`] + financials fetch, `asyncio.gather`-batched,
`_PEER_FETCH_BATCH_SIZE = 5` at a time → `peer_multiples()`). Stops once
`_TARGET_PEER_COUNT = 5` peers are assembled or
`_MAX_PEER_CANDIDATES_TRIED = 15` candidates have been attempted. Fewer
than `_MIN_PEER_COUNT_FOR_COMPS = 2` peers found is an explicit
`CoverageGap`, not a crash — `peer_multiples()` already handles 0-1 peers
gracefully via `_median_ignoring_none`. Raises `PeerDiscoveryError` only
when the *target's own* `PeerFinancials` can't be built (a company with
real filings and market data essentially always has a resolvable price and
shares_outstanding, so this signals a genuine system problem, not a
routine coverage gap — contrast with a candidate peer being unresolvable,
which is expected/routine and simply excludes that candidate).

## Phase 2 golden fixtures

All real, captured live (per this project's "never hand-constructed" golden-file
rule) via a properly-`User-Agent`-headered `curl`/`httpx` request — a plain
unauthenticated fetch of `sec.gov` (e.g. a generic web-fetch tool) returns HTTP
403, same bot-detection posture as Stooq (Phase 0):
- `overstock_8k_transcript_sample.html` — the real Ex-99.1 transcript exhibit
  (CIK 1130713, accession 0001130713-15-000020), `overstock_8k_primary_sample.html`
  — that accession's primary 8-K document (for contrast — has no transcript-shaped
  text itself), `overstock_submissions_sample.json` / `overstock_accession_index_sample.json`
  — supporting fixtures for the full `EdgarClient.get_transcript_input()` test.
  **Note**: this filing is old enough (2015) to have aged out of EDGAR's
  `submissions.json` `filings.recent` array (which only retains recent history);
  the trimmed submissions fixture's one entry was reconstructed from real,
  independently-sourced values (the real accession/primaryDocument from the
  live `index.json`, filingDate from that index's `last-modified` timestamp,
  reportDate from the transcript's own stated call date) rather than lifted
  directly from a live `recent` array the way the other fixtures were — flagged
  here since it's a different sourcing path than every other golden fixture
  in this repo.
- `predictivetech_8k_item401_sample.html` (real auditor-dismissal 8-K),
  `mbuu_8k_item502_sample.html` (real officer-departure/appointment 8-K, from
  Malibu Boats' own real recent filing history), `emergentbio_8k_item402_sample.html`
  (real restatement 8-K) — one real example per checklist-relevant 8-K item type.
- `vividseats_10k_material_weakness_sample.html` — a real 10-K/A (CIK 1856031)
  amending Item 9A to disclose a genuine material weakness.
- `mbuu_10k_sample.html`, `mbuu_8k_latest_202_sample.html`,
  `mbuu_8k_item502_sample.html`, `mbuu_submissions_sample.json` — one real
  filer's (Malibu Boats) own 10-K plus two of its own real 8-Ks (one routine,
  one 5.02, four positions back in the same filer's real 8-K history), used
  together to test the lookback-scan merge end-to-end via `EdgarClient`
  itself, not just the underlying parsing functions in isolation.

## Phase 4 golden fixtures

- `sic7370_browse_edgar_sample.xml` — real, live-captured SEC EDGAR SIC-browse atom feed (SIC 7370,
  GOOGL's own SIC code), trimmed to 3 entries + the real pagination footer. Confirms the feed's
  `name`/`title` fields are unusable (`"ARRAY(0x...)"`) and that `<cik>` is the only reliable field.
- `googl_shares_outstanding_concept.json` — real, live-captured, trimmed
  `us-gaap:CommonStockSharesOutstanding` companyconcept payload for GOOGL, same shape/style as the
  existing `googl_revenue_concept.json`. Confirms this tag resolves to one combined ~12B-share
  figure for GOOGL despite its multiple share classes, no per-class dimensional handling needed.
