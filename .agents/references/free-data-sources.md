# Free Data Sources for the Agentic Fundamental Analyst (MVP)

Research date: 2026-08-17. Verified against primary/official sources where fetchable; SEC.gov itself
blocks automated WebFetch requests (403, likely bot-detection on the fetch tool's own UA — ironic given the
User-Agent requirement described below), so SEC facts are corroborated via multiple secondary sources
(tldrfiling.com's SEC API guides, dealcharts.org) that quote the SEC's own published rules consistently.
Everything else below is fetched from official pricing/docs pages directly.

Guiding principle for this document: **"free" means usable for constant testing at zero marginal cost,
not "has a free trial" or "has a free tier that returns 25 requests/day."** Where a nominally-free tier is
too thin to build on, that is called out explicitly rather than glossed over.

---

## 1. SEC EDGAR — filings + structured financial data

**Base host:** `data.sec.gov` (structured JSON APIs), `www.sec.gov` (document archive), `efts.sec.gov`
(full-text search). All are free, no API key, no signup.

### Auth / access requirements
- **No API key.** But every request MUST include a descriptive `User-Agent` header, e.g.:
  `User-Agent: YourAppName your-email@example.com`
- Requests lacking a proper User-Agent are commonly rejected with 403.
- **Rate limit: 10 requests/second per IP**, enforced across `www.sec.gov`, `data.sec.gov`, and
  `efts.sec.gov` combined. Exceeding it triggers a temporary IP block (roughly on the order of minutes).
- Practical guidance from the community: throttle to ~8 req/s, use exponential backoff on 403/429,
  cache aggressively (company data changes infrequently), and never fire concurrent/parallel requests.
- For bulk needs, SEC publishes `companyfacts.zip` and `submissions.zip` bulk archives — better than
  looping per-company if you need broad coverage rather than single-ticker lookups.

### Endpoints

**Submissions API** — filer history (recent filings, forms, dates, accession numbers, primary docs):
```
GET https://data.sec.gov/submissions/CIK##########.json   (10-digit zero-padded CIK)
```

**Company Facts (XBRL)** — all structured financial concepts reported by one company, across taxonomies:
```
GET https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
```

**Company Concept (XBRL)** — single concept's full time series for one company (lighter payload than
companyfacts when you only need e.g. revenue):
```
GET https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/Revenues.json
```

**Frames (XBRL)** — one concept across *all* companies for a given period, useful for cross-sectional
comparison:
```
GET https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2024.json
```

**Full-Text Search** — search inside filing text (10-K/10-Q/8-K bodies and exhibits), covers filings
from 2001-05-04 onward:
```
GET https://efts.sec.gov/LATEST/search-index?q=%22...%22&forms=8-K&dateRange=custom&startdt=...&enddt=...
```
No API key required; a normal browser-like User-Agent is tolerated here even though SEC's stated policy
still asks for identification. Treat this endpoint as functionally public but *unversioned/undocumented*
(the `LATEST` path segment implies versioning that doesn't actually exist) — don't build brittle
assumptions about its query-param surface staying stable.

### Known gotchas (important for the deterministic data layer)
- **XBRL tag inconsistency across companies.** Different filers use different us-gaap tags for
  conceptually similar line items — e.g. some report `Revenues`, others
  `RevenueFromContractWithCustomerExcludingAssessedTax`. A companyconcept lookup for one tag can come back
  empty for a company that simply used a different tag, not because the data doesn't exist. Any extraction
  logic needs a fallback list of tag aliases per concept (revenue, net income, EPS, assets, etc.) and must
  be resilient to "concept not found" without assuming the company has no operations.
- **Non-calendar fiscal years.** The `frames` endpoint uses `CY{year}` (calendar-year) framing, but
  individual companies report on their own fiscal calendars (e.g. Apple's fiscal year ends late September,
  Microsoft's ends June 30). Cross-company period alignment via frames data will silently include
  companies whose "CY2024" bucket is actually skewed relative to a calendar year — always check the
  `fy`/`fp`/`frame`/`start`/`end` fields per data point rather than trusting the URL's year label alone.
- Missing data for a concept usually means "this filer didn't tag it that way," not "this filer has zero
  of this metric" — don't conflate absence with zero.

---

## 2. FRED (Federal Reserve Economic Data) — macro series

**Official docs:** https://fred.stlouisfed.org/docs/api/fred/
**Registration:** https://fredaccount.stlouisfed.org — free, instant, email-based signup, no contract,
no approval wait, no credit card.

### Access / rate limits
- Genuinely free, one tier, no enterprise upsell — every registered user gets identical access to 800,000+
  series from 100+ source agencies.
- **Correction (Phase 0 execution, 2026-08): `api_key` is required unconditionally, not optional.**
  A keyless request to `/fred/series/observations` returns HTTP 400
  `"Variable api_key is not set"` — confirmed directly, not "works keyless at 30 req/min" as this
  section originally stated. With a key: 120 req/min.
- Schema is extremely stable: series IDs don't change, response envelope hasn't materially changed in a
  decade. Low risk of breakage over the life of the MVP.

### Core endpoint
```
GET https://api.stlouisfed.org/fred/series/observations
    ?series_id={ID}&api_key={KEY}&file_type=json&observation_start=YYYY-MM-DD
```
Up to 10,000 observations per request; missing values render as the string `"."` and need explicit
numeric coercion in a Pydantic validator.

### Series relevant to equity macro-sensitivity analysis
| Series ID | What it is | Why relevant |
|---|---|---|
| `FEDFUNDS` | Effective Fed Funds Rate | Discount-rate / cost-of-capital sensitivity |
| `DGS10` | 10-Year Treasury yield | Equity risk premium, valuation multiple sensitivity |
| `DGS2` | 2-Year Treasury yield | Short-rate expectations |
| `T10Y2Y` | 10Y–2Y spread | Widely used recession/regime signal |
| `CPIAUCSL` | CPI, all urban consumers | Inflation exposure, input-cost sensitivity |
| `PCEPI` | PCE Price Index | Fed's preferred inflation gauge |
| `GDP` / `GDPC1` | Nominal / Real GDP | Cyclicality, top-line macro beta |
| `UNRATE` | Unemployment rate | Consumer-discretionary demand proxy |
| `INDPRO` | Industrial Production Index | Industrials/cyclicals exposure |
| `DTWEXBGS` | Trade-weighted USD index | FX sensitivity for multinationals |
| `SP500` | S&P 500 daily close (FRED mirror) | Market beta context, though a dedicated price source is better for this (see §3) |
| `VIXCLS` | CBOE Volatility Index | Risk-regime/vol context |
| `M2SL` | M2 money supply | Liquidity conditions |

This is the strongest, lowest-risk source in the whole stack — free, official, stable, well-documented.

---

## 3. Price data — historical daily OHLCV

Evaluated five realistic free options. Honest comparison:

| Source | Free tier | Auth | Reliability verdict |
|---|---|---|---|
| **yfinance / Yahoo unofficial** | Unlimited nominally | None | **Fragile.** Not an official API — it scrapes Yahoo's web/chart endpoints. Yahoo actively rate-limits and IP-blocks scraping patterns; `YFRateLimitError` reports are frequent and recent (through 2026). Works fine at low, human-like request rates with caching, but is not something to build a "test constantly" workflow on without accepting intermittent breakage. No SLA, no versioning guarantee — Yahoo can and does change response shapes without notice. |
| **Stooq** | Unlimited-ish, but undocumented daily quota | None | **Correction (Phase 0 execution, 2026-08): now blocked for programmatic use.** `stooq.com/q/d/l/?s=TICKER&i=d` returns a JavaScript proof-of-work challenge page instead of CSV — confirmed via `curl` (real browser User-Agent) and a markdown-conversion fetch tool, neither of which can execute the required JS. This is a bot-detection change since this section was originally researched; the "no key, plain CSV over HTTP" description below no longer holds. Blocked pending a headless-browser fetch path — see `data/stooq.py`'s docstring. |
| **Alpha Vantage (free)** | **25 requests/day**, 5/min | API key (instant, free) | Too thin to build on. 25 requests/day is roughly "look up one ticker's history once, then you're done for the day" — incompatible with "team testing constantly." Officially confirmed on their 2026 pricing page context; paid plans start at $49.99/mo. |
| **Twelve Data (free)** | 800 requests/day, 8/min, 5,000 datapoints/request | API key (free) | Usable but tight for iterative dev (8/min is very slow for anything batch-like); free tier covers US equities/forex/crypto only. |
| **Tiingo (free "Starter")** | **1,000 requests/day, 50/hour**, 1GB bandwidth/month | API key (free signup) | Official, documented REST API (not scraping) with **30+ years of EOD price history**, ~110,000 global securities including ~49,000 US/China stocks. Rate limit is generous enough for iterative single-ticker development and light batch use. This is the most stable, most "real API" free option evaluated. |

### Recommendation
**Tiingo free tier** is the best-supported choice: it's an actual documented, versioned REST API (not a
scrape), free signup with no credit card, rate limits (1,000/day, 50/hour) that comfortably support a
small team hitting one ticker at a time repeatedly during development, and deep historical daily coverage.

Fall back to **Stooq CSV bulk download** for one-time/offline historical backfills where you want a whole
price history in one shot and don't want to burn Tiingo's daily quota, and keep **yfinance** only as an
opportunistic secondary/cross-check source, not a primary dependency, given its documented fragility.

Note: **IEX Cloud**, once a common "IEX Cloud successor" reference point, fully shut down August 31, 2024
with no official replacement product — it is not an option and several "IEX Cloud alternative" roundups
now just point to Tiingo, Alpha Vantage, or paid providers (Polygon, Intrinio, EODHD, Databento).

---

## 4. Earnings call transcripts — honest verdict: **no good systematic free source**

This is the category to be most honest about.

- **Dedicated transcript APIs are paid.** API Ninjas' Earnings Call Transcript API is explicitly
  "Premium Only" — no functional free tier at all (a free *key* exists for other API Ninjas endpoints, but
  this specific one requires a paid plan, and even paid free-adjacent access forbids commercial use).
  Finnhub gates transcript retrieval and earnings-call audio behind its paid tier even though other
  fundamentals are free. Alpha Vantage has a transcript endpoint but it's subject to the same 25 req/day
  free-tier ceiling described in §3, making it impractical. Financial Modeling Prep and Roic AI have
  transcript endpoints but with narrow free allowances (e.g. Roic AI free tier: 5 req/min, only 2 years of
  history).
- **IR sites** frequently post transcripts (PDF or HTML), but there is no unified, machine-readable, free
  API across companies — this would mean per-company scraping with no consistent format and uncertain
  terms-of-use, which doesn't fit a deterministic, maintainable data layer.
- **SEC 8-K exhibits are the one genuinely free, systematic angle — but partial.** Some companies furnish
  a verbatim earnings-call transcript as Exhibit 99.1/99.2 on an 8-K (filed under Item 8.01 or Item 9.01,
  "furnished" not "filed"). These are retrievable for free via the EDGAR full-text search API (§1) by
  searching for `forms=8-K` plus phrase matches, and the documents themselves live at ordinary
  `www.sec.gov/Archives/edgar/...` URLs with the same free/no-key access. However, coverage is estimated
  at only roughly **20–30% of filers** — most companies file only the press release (Ex-99.1) and skip the
  transcript, or don't furnish one at all. Coverage is inconsistent by company and even by quarter for the
  same company.

**Recommendation: defer full-transcript-based analysis (qualitative management-tone extraction, guidance
language parsing, Q&A synthesis) from the MVP scope.** Where an 8-K exhibit transcript happens to exist for
a given ticker/quarter (discoverable via EDGAR full-text search), it's fair game to use opportunistically
and cite as a primary source — but the system must not assume a transcript is available, and the memo
should not silently degrade to "summarizing the press release" while presenting it as call-transcript
analysis. If transcripts are material to the product vision, that's a paid-source decision for a future
phase (e.g. AlphaSense, Bloomberg, or a mid-tier paid transcript API), not something to fake with a thin
free tier.

---

## 5. Analyst estimates / consensus data — honest verdict: **mostly defer**

- **Consensus EPS/revenue estimates, price targets:** These are commercial, aggregated sell-side data
  products at their core (the underlying analyst estimates come from IBES/Refinitiv, FactSet, Visible
  Alpha, etc.). Every free-tier provider that has these (FMP, Intrinio, Tradefeeds, Finnhub) either paywalls
  them entirely or exposes only a thin slice:
  - **Finnhub free tier**: price-target endpoint is explicitly Premium-only. But two genuinely free crumbs
    exist: the **recommendation-trends** endpoint (buy/hold/sell analyst counts over time, no price target)
    and **EPS surprise** history (actual vs. estimated EPS for the last 4 reported quarters) — both usable
    on the free 60 req/min tier.
  - **Financial Modeling Prep**: markets a "Price Target Consensus" and "Financial Estimates" API, but
    these sit behind FMP's paid plans in practice; the nominally-free FMP tier is oriented around basic
    fundamentals/statements, not consensus estimates.
  - No provider surfaced in this research offers full free consensus EPS/revenue estimate distributions or
    genuine price-target aggregation without a paid plan.

**Recommendation: defer consensus estimates and price targets from MVP scope entirely**, with one narrow
exception worth keeping: Finnhub's free **recommendation-trends** (sentiment counts) and **EPS surprise**
(historical beat/miss) endpoints are free, real, and can support a limited "how has this company tracked
vs. expectations historically" section without claiming to have forward consensus numbers. Do not
represent anything derived from these two free endpoints as "consensus estimates" or "price targets" in
the memo — they are backward-looking beat/miss history and sentiment counts only, not forecasts.

---

## Recommended MVP source list

| Data need | Source | Why |
|---|---|---|
| Filings (10-K/10-Q/8-K), structured financial statement data | **SEC EDGAR** (`data.sec.gov` submissions + XBRL companyfacts/companyconcept, `efts.sec.gov` full-text search) | Official, authoritative, genuinely unlimited (10 req/s), zero-key, primary source for grounding. Build tag-alias fallbacks for XBRL inconsistency. |
| Macro series (rates, inflation, GDP, unemployment, USD, VIX) | **FRED** (`api.stlouisfed.org/fred/series/observations`) | Official Fed source, free instant key, 120 req/min, extremely stable schema, comprehensive series relevant to macro-sensitivity analysis. |
| Historical daily prices (OHLCV) | **Tiingo free tier** | Real documented/versioned REST API, free key, 1,000 req/day / 50/hour is workable for constant dev/testing, 30+ years history, ~110k securities. Use **Stooq CSV** as a bulk/offline backfill supplement. |
| Backward-looking earnings-beat history / analyst sentiment counts | **Finnhub free tier** (recommendation-trends, EPS surprise endpoints only) | The only genuinely free, systematic crumbs of "analyst view" data; clearly label as historical beat/miss and sentiment counts, not forecasts. |
| Opportunistic transcript excerpts, when they exist | **SEC EDGAR full-text search over 8-K exhibits** | Free, same infra as filings, but only ~20-30% coverage — use if found, never assume present. |

## Deferred / not available free (explicitly out of MVP scope)

- **Full earnings-call transcript analysis** (management tone, Q&A synthesis, guidance-language parsing)
  as a *reliable, general* capability — no free source has consistent cross-company coverage. Only
  opportunistic use of SEC 8-K exhibit transcripts (when they happen to exist) is in scope; do not build
  a feature that assumes a transcript will be available.
- **Consensus analyst EPS/revenue estimates** (forward-looking, aggregated across analysts) — no free
  source found; all real consensus-estimate products are paid.
- **Analyst price targets** (individual or consensus) — paywalled everywhere checked (Finnhub, FMP, etc.).
- **Real-time/intraday pricing** — out of scope for a memo tool anyway, but worth noting free tiers
  generally restrict real-time quotes to paid plans (Tiingo, Twelve Data, Alpha Vantage all gate real-time
  behind paid tiers; free tiers are EOD/delayed).
- **IEX Cloud** as a data source — the service no longer exists (shut down August 31, 2024, no official
  successor).

---

## Sources consulted
- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces (blocked
  direct fetch; corroborated via) https://tldrfiling.com/blog/sec-edgar-api-rate-limits-best-practices ,
  https://tldrfiling.com/blog/sec-edgar-api-guide , https://tldrfiling.com/blog/sec-edgar-full-text-search-api
- FRED API docs: https://fred.stlouisfed.org/docs/api/fred/ (registration/rate-limit detail corroborated
  via https://econindx.com/guides/getting-started-fred/ )
- Tiingo pricing: https://www.tiingo.com/about/pricing
- Alpha Vantage 2026 pricing context: https://alphalog.ai/blog/alphavantage-api-complete-guide ,
  https://www.alphavantage.co/iexcloud_shutdown_analysis_and_migration/
- Twelve Data pricing: https://twelvedata.com/pricing
- Stooq limitations: https://www.quantstart.com/articles/an-introduction-to-stooq-pricing-data/ ,
  community reports of "Exceeded the daily hits limit"
- yfinance rate-limit issues: https://github.com/ranaroussi/yfinance/discussions/2431 ,
  https://github.com/ranaroussi/yfinance/issues/2289
- IEX Cloud shutdown: https://blog.infoway.io/en/iex-cloud-shut-down-in-2024-heres-how-to-migrate-your-stock-data-integration/
- API Ninjas transcript API (premium-only): https://api-ninjas.com/api/earningscalltranscript
- Finnhub transcript/price-target gating: https://finnhub.io/docs/api/earnings-call-transcripts-api ,
  https://finnhub.io/docs/api/recommendation-trends
- 8-K transcript exhibit prevalence: example filings on sec.gov/Archives/edgar (e.g.
  https://www.sec.gov/Archives/edgar/data/1130713/000113071315000020/a8-kq115earningscalltransc.htm )
- FMP analyst estimates/price target positioning: https://site.financialmodelingprep.com/developer/docs/stable/price-target-consensus
