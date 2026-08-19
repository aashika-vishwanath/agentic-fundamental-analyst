# Data Layer — Implementation Reference

Status: built, Phase 0 complete. Covers `EdgarClient`/`FredClient`/`PriceClient`,
the cache layer, filing-section parsing, XBRL tag aliases, SIC exclusion, and
`fetch_all()` — as actually built, not as researched. For source API research
(endpoints, rate limits, auth), see `free-data-sources.md`.

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
    valuation.py                # DCFScenario, DCFResult, PeerFinancials, PeerMultiples, PeerCompsResult
  data/
    cache.py              # cached() decorator, diskcache-backed, keyed on (source, func, args, kwargs)
    excluded_sic.py         # bank/insurer/REIT SIC code -> ExcludedSector map
    tag_aliases.py            # per-concept us-gaap tag fallback lists (13 concepts)
    edgar.py                    # EdgarClient: submissions, XBRL concepts, filings, intake
    filing_sections.py            # pure HTML parsing: 10-K Item 1/1A/7, 8-K item bodies
    fred.py                        # FredClient
    tiingo.py                       # TiingoClient, PriceClient
    stooq.py                         # BLOCKED — see module docstring
    fetch.py                          # fetch_all(ticker) -> gated on TickerIntakeResult.in_scope
  ratios.py                # DSO, Sloan accruals, cash conversion, capex/D&A, Beneish (8 components), CCC
  valuation.py              # dcf() bull/base/bear, peer_multiples()
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
order, and merges every filer's fact stream into `FiscalPeriod` rows. Two
non-obvious bugs found and fixed by testing against live data (both are
now regression-tested in `tests/unit/test_edgar_client.py`):

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

`get_filing_sections(cik10)` parses the latest 10-K's Item 1/1A/7 and the
latest 8-K's item bodies — see `filing_sections.py` below for the parsing
approach. Coverage gaps are per-field, never a blanket failure.

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

## `fetch_all()` (`data/fetch.py`)

Gated on `TickerIntakeResult.in_scope` — raises `TickerOutOfScope` (not a
`Union` return, unlike the plan's original sketch; kept consistent with
this codebase's existing typed-exception pattern — `EdgarError`,
`FredError`, `TiingoError`) before any other fetch for an excluded ticker.
Returns `(FinancialStatementBundle, FilingSections, list[MacroSeriesBundle],
PriceHistory)` — a list of macro bundles (one per FRED series in
`_MACRO_SERIES_IDS`), not a single bundle, since a memo needs several
series (10Y yield, Fed funds, 10Y-2Y spread).
