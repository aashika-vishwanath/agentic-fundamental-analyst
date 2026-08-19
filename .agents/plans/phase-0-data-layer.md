# Feature: Phase 0 — Deterministic Data Layer

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

**Status: PLANNING ONLY.** No code, dependencies, or data files exist yet as a result of this plan. All API sample capture described below happens at `/execute` time, not during planning (see NOTES).

## Feature Description

Build the deterministic, non-agent foundation the entire pipeline depends on: typed clients for SEC EDGAR, FRED, and Tiingo/Stooq; a local cache layer; XBRL tag-alias resolution; filing-section parsing; ratio math; valuation math; and the SIC-code sector-exclusion check (PRD §7). No LLM or agent code exists in this phase — everything here is plain, unit-tested Python.

## User Story

As the system builder, I want a fully typed, cached, unit-tested data-fetching and computation layer, so that every later agent receives validated, traceable, typed inputs and never has to fetch or compute anything itself.

## Problem / Solution Statement

Without this layer, later agents would either fetch/compute things themselves (violating the core agents-interpret/code-computes principle) or receive untyped, unreliable inputs that can't be grounded deterministically. Solution: build and golden-file-test this layer completely before any agent exists, so Phase 1 onward can assume validated typed inputs are simply available.

Alternative rejected: giving each agent its own data-fetching dependency (e.g. an `httpx` client injected via `deps_type`) and letting it call APIs directly. Rejected because it breaks the deterministic/agent boundary (PRD §4), makes API costs and flakiness leak into agent evals, and makes the `GroundingEvaluator` unable to cleanly check "does this number trace to a typed input field" — there'd be no stable input snapshot to check against.

## Feature Metadata

**Type**: New Capability &nbsp;&nbsp; **Complexity**: Medium-High (three independent external APIs, parsing, and financial math — no LLM/agent complexity) &nbsp;&nbsp; **Pipeline stage(s)**: Phase 0, precedes all agents &nbsp;&nbsp; **Dependencies**: none (first phase)

## Agent-or-Code Decisions

| Component | Agent or Code | Why |
|---|---|---|
| `EdgarClient` | Code | Fetching structured/text data from an API is mechanical; no interpretation |
| `FredClient` | Code | Same |
| `PriceClient` (Tiingo + Stooq) | Code | Same |
| Cache layer | Code | Pure infrastructure |
| Filing section extraction (HTML/text → typed sections) | Code | Deterministic parsing (regex/HTML-tag boundaries on well-known SEC document structure), not judgment about what the text means |
| XBRL tag-alias resolution | Code | A fixed lookup table per concept, not a judgment call |
| `ratios.py` (DSO, Sloan accruals, cash conversion, capex/D&A, Beneish components, cash conversion cycle) | Code | Arithmetic on typed inputs, golden-file testable |
| `valuation.py` (DCF, peer multiples) | Code | Arithmetic given disclosed assumptions; the *interpretation* of the result is the Valuation Interpreter agent's job (Phase 4), not this layer's |
| SIC-code sector-exclusion check | Code | A lookup against a fixed excluded-SIC-code list, run at intake before anything else |

Nothing in this phase is an agent — this table exists to make that explicit and checkable, per `CLAUDE.md`'s Hard Constraints.

## Data Contracts

```python
# --- financials ---

class CoverageGap(BaseModel):
    field: str
    reason: str  # e.g. "no_xbrl_tag_alias_resolved", "sector_excluded", "pre_ipo_no_data"

class XBRLFact(BaseModel):
    tag: str
    taxonomy: str            # "us-gaap"
    unit: str                 # "USD"
    value: float
    period_start: date | None
    period_end: date
    fiscal_year: int
    fiscal_period: str        # "Q1" | "Q2" | "Q3" | "Q4" | "FY"
    form: str                 # "10-Q" | "10-K"
    accession_number: str
    filed_date: date

class FiscalPeriod(BaseModel):
    fiscal_year: int
    fiscal_period: str
    form: str
    period_end: date
    revenue: float | None
    net_income: float | None
    capex: float | None
    depreciation_amortization: float | None
    accounts_receivable: float | None
    inventory: float | None
    total_assets: float | None
    operating_cash_flow: float | None
    # Optional throughout by design — a None here is always paired with a
    # CoverageGap entry on the parent bundle, never silently treated as zero.

class FinancialStatementBundle(BaseModel):
    ticker: str
    cik: str
    periods: list[FiscalPeriod]   # multi-period, most recent first
    coverage_gaps: list[CoverageGap]

# --- filings ---

class FilingMetadata(BaseModel):
    accession_number: str
    form: str
    filed_date: date
    period_of_report: date | None
    primary_document_url: str
    items: list[str]    # 8-K item numbers, e.g. ["4.01", "5.02"]

class FilingSections(BaseModel):
    accession_number: str
    item_1_business: str | None
    item_1a_risk_factors: str | None
    item_7_mdna: str | None
    eightk_item_bodies: dict[str, str]   # item number -> extracted text
    coverage_gaps: list[CoverageGap]

# --- macro ---

class MacroSeriesPoint(BaseModel):
    obs_date: date
    value: float | None   # None when FRED returns its "." missing-value sentinel

class MacroSeriesBundle(BaseModel):
    series_id: str
    points: list[MacroSeriesPoint]

# --- prices ---

class PriceBar(BaseModel):
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float

class PriceHistory(BaseModel):
    ticker: str
    source: Literal["tiingo", "stooq"]
    bars: list[PriceBar]

# --- intake / scope enforcement ---

class ExcludedSector(str, Enum):
    BANK = "bank"
    INSURER = "insurer"
    REIT = "reit"

class TickerIntakeResult(BaseModel):
    ticker: str
    cik: str
    sic_code: str
    sic_description: str
    in_scope: bool
    exclusion_reason: ExcludedSector | None
```

Optional-field policy: every field that can be legitimately absent (unresolved XBRL tag, missing FRED observation, no 8-K exhibit) is `Optional`/`None`, and every `None` in a per-period or per-bundle model is paired with a `CoverageGap` entry — never coerced to `0.0` or silently dropped. This is the concrete implementation of PRD principle #4.

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing
None — this is the first code written in the repository. Nothing to mirror; this phase *establishes* the pattern later phases will follow (per `CLAUDE.md`'s Conventions section).

### New files to create
```
pyproject.toml
src/agentic_fundamental_analyst/
  data/
    cache.py
    edgar.py
    fred.py
    tiingo.py
    stooq.py
    tag_aliases.py       # per-concept XBRL tag alias lists
    excluded_sic.py       # SIC-code exclusion list (banks/insurers/REITs)
  contracts/
    financials.py
    filings.py
    macro.py
    prices.py
    intake.py
  ratios.py
  valuation.py
tests/
  golden/                 # populated at /execute time — see NOTES
  unit/
    test_edgar_client.py
    test_fred_client.py
    test_price_client.py
    test_ratios.py
    test_valuation.py
    test_intake.py
```

### Documentation to READ before implementing
- `.agents/references/free-data-sources.md` — endpoints, rate limits, known gotchas (tag inconsistency, non-calendar fiscal years, FRED missing-value sentinel)
- `PRD.md` §5 (Data Layer Specification), §6 (Data Contracts), §7 (Company Universe / MVP Scope)
- Official docs: `https://www.sec.gov/search-filings/edgar-application-programming-interfaces`, `https://fred.stlouisfed.org/docs/api/fred/`, `https://www.tiingo.com/documentation/end-of-day`

### Patterns to follow
None yet exist in-repo. The client modules should share one convention going forward: an async method per endpoint, a Pydantic model as the return type (never a raw dict), and every network call routed through the shared cache layer — later phases mirror whatever pattern gets established here.

---

## IMPLEMENTATION PLAN

### Phase A: Contracts & Data
- Define all contracts above under `contracts/`
- `uv init`; add `httpx`, `pydantic`, `python-dotenv`, cache backend (`diskcache` or stdlib `sqlite3`), `pytest`, `pytest-asyncio`, lint/type tooling (`ruff`, `pyright`)

### Phase B: Core Implementation
- `cache.py` — generic cache wrapper keyed by `(source, endpoint, params)`, TTL per source (7d filings/XBRL, 1d macro/prices, per PRD §5)
- `edgar.py` — `submissions()`, `company_concept()`, `full_text_search()`; routes every concept lookup through `tag_aliases.py`'s fallback list, emitting a `CoverageGap` (never a false zero) when no alias resolves
- `excluded_sic.py` + intake check — resolves `TickerIntakeResult` from a ticker's SIC code, run before any other fetch
- `fred.py` — `observations(series_id)`, coercing the `"."` sentinel to `None`
- `tiingo.py` (primary) + `stooq.py` (bulk backfill fallback) — unified under `PriceClient`
- `ratios.py` — pure functions for every checklist item from the memo skill: DSO, Sloan accruals, cash conversion ratio, capex/D&A ratio, Beneish components, cash conversion cycle
- `valuation.py` — DCF (FRED risk-free rate + disclosed equity-risk-premium assumption) and peer-multiple construction from SIC-matched peers

### Phase C: Integration
- No pipeline exists yet (that starts Phase 1). Deliverable here is a single `fetch_all(ticker) -> TickerIntakeResult | (FinancialStatementBundle, FilingSections, MacroSeriesBundle, PriceHistory)` convenience function, gated on `in_scope` — this is what Phase 1's analyst will call, so its shape matters even though nothing consumes it yet.

### Phase D: Evals & Validation
No Pydantic Evals dataset applies — there's no LLM output to score. Golden-file unit tests serve the equivalent "don't ship without proof" gate for this phase (PRD §8's bottom layer).

---

## STEP-BY-STEP TASKS

### CREATE `pyproject.toml`
- **IMPLEMENT**: uv-managed project, Python 3.12+, deps listed in Phase A
- **VALIDATE**: `uv sync`

### CREATE `src/agentic_fundamental_analyst/contracts/financials.py`
- **IMPLEMENT**: `CoverageGap`, `XBRLFact`, `FiscalPeriod`, `FinancialStatementBundle`
- **VALIDATE**: `uv run python -c "from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle"`

### CREATE `src/agentic_fundamental_analyst/contracts/filings.py`, `macro.py`, `prices.py`, `intake.py`
- **IMPLEMENT**: remaining models from Data Contracts above
- **VALIDATE**: same import-smoke pattern

### CREATE `src/agentic_fundamental_analyst/data/cache.py`
- **IMPLEMENT**: `cached(source: str, ttl: timedelta)` decorator/wrapper around async fetch functions, keyed on function args
- **GOTCHA**: cache key must include all query params, not just the ticker — two different date ranges for the same ticker are different cache entries
- **VALIDATE**: unit test with a fake fetch function proving second call doesn't re-invoke it within TTL

### CREATE `src/agentic_fundamental_analyst/data/excluded_sic.py`
- **IMPLEMENT**: SIC code → `ExcludedSector` mapping (banks: 6020-6036 range; insurers: 6311-6411 range; REITs: 6798) — verify exact SIC ranges against SEC's own SIC code list during execute, don't guess
- **VALIDATE**: unit test against known real CIKs (a bank, an insurer, a REIT, and Alphabet as the non-excluded control)

### CREATE `src/agentic_fundamental_analyst/data/tag_aliases.py`
- **IMPLEMENT**: per-concept fallback list, e.g. `revenue: ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]`
- **PATTERN**: informed by `.agents/references/free-data-sources.md`'s tag-inconsistency gotcha
- **VALIDATE**: unit test resolving revenue for two companies known to use different tags

### CREATE `src/agentic_fundamental_analyst/data/edgar.py`
- **IMPLEMENT**: `EdgarClient.submissions(cik)`, `.company_concept(cik, tag)` (tries each alias in order), `.full_text_search(query, forms)`
- **GOTCHA**: mandatory `User-Agent: <app name> <real email>` header or requests 403; throttle to ~8 req/s, exponential backoff on 403/429
- **VALIDATE**: unit test against a captured golden fixture (network-free); a separate, explicitly-marked live smoke test hits the real API

### CREATE `src/agentic_fundamental_analyst/data/fred.py`
- **IMPLEMENT**: `FredClient.observations(series_id, start=None)`; coerce `"."` to `None`
- **GOTCHA**: `api_key` is a **required** query param on every call — confirmed directly (a keyless request returns HTTP 400 `"Variable api_key is not set"`), not merely rate-limited as the initial research doc suggested (see NOTES)
- **VALIDATE**: unit test on a captured golden fixture

### CREATE `src/agentic_fundamental_analyst/data/tiingo.py`, `stooq.py`
- **IMPLEMENT**: `PriceClient` wrapping both; Tiingo primary via documented REST endpoint + token header, Stooq as CSV-parsing fallback
- **VALIDATE**: unit test on captured golden fixtures for both

### CREATE `src/agentic_fundamental_analyst/ratios.py`
- **IMPLEMENT**: one pure function per checklist item (see memo skill §2) — each takes typed `FiscalPeriod`/period-pairs, returns a float or `None` + reason if inputs are missing
- **VALIDATE**: golden-file tests with hand-verified expected values

### CREATE `src/agentic_fundamental_analyst/valuation.py`
- **IMPLEMENT**: `dcf(cash_flows, discount_rate, terminal_growth) -> DCFResult` (bull/base/bear via assumption variants); `peer_multiples(target, peers) -> PeerCompsResult`
- **VALIDATE**: golden-file tests against a hand-computed synthetic scenario (doesn't require real market data — a fixed, documented cash-flow series is enough to prove the math)

### CREATE `fetch_all()` convenience function
- **IMPLEMENT**: runs `TickerIntakeResult` check first; short-circuits with a clear rejection if `in_scope=False`; otherwise fetches+assembles all four bundles
- **VALIDATE**: integration-style unit test using golden fixtures end to end

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe)
All of the above — must pass with **zero network access and zero API keys**, using only golden fixtures. This is the CI contract per `CLAUDE.md`.

### Eval dataset (Pydantic Evals)
Not applicable to this phase — no agent, no LLM output to score. Golden-file tests are the phase-appropriate substitute for the "no agent ships without an eval dataset" rule.

### Edge cases
- XBRL tag not found under any alias → `CoverageGap`, never a false `0.0`
- FRED `"."` values → coerced to `None`, not `0.0`
- Non-calendar fiscal year (e.g. a company with a June or September fiscal year-end) → periods correctly labeled via `fy`/`fp`/`start`/`end`, not assumed calendar-aligned
- SEC rate limit (403/429) → exponential backoff, not immediate failure or silent empty result
- Tiingo daily-quota exhaustion (429) → clear, typed error surfaced; falls back to Stooq if configured to
- Recently-IPO'd company with <5 years of filed history → fewer `FiscalPeriod` entries, not an error
- Excluded-sector ticker (bank/insurer/REIT) → `TickerIntakeResult.in_scope=False` with a specific `exclusion_reason`, and `fetch_all()` short-circuits before making any other API call

---

## VALIDATION COMMANDS

### Level 1: Syntax & style — `uv run ruff check . && uv run pyright`
### Level 2: Unit tests — `uv run pytest tests/unit -q` (must pass with no network, no keys)
### Level 3: N/A — no eval dataset in this phase
### Level 4: Manual — live smoke run against real EDGAR/FRED/Tiingo for one ticker (Alphabet recommended, see NOTES), requires real FRED + Tiingo keys in `.env`; confirm no exceptions and that a second identical call is served from cache, not a second live request
### Level 5: N/A — no pipeline exists yet to integrate against

---

## ACCEPTANCE CRITERIA
- [x] Contracts match this plan exactly; no untyped (`dict`) boundaries introduced anywhere — with documented extensions, see Execution Deviations below
- [x] All validation levels pass; unit suite is 100% network-free and key-free (verified by running with `.env` removed)
- [x] SIC-exclusion check correctly rejects a real bank/insurer/REIT ticker with a specific reason, and accepts a real non-financial ticker (JPM/O/MET rejected, GOOGL/AAPL accepted, live and in tests)
- [x] Every `CoverageGap` path is exercised by a test — no code path silently turns "missing" into "zero"
- [x] `CLAUDE.md`'s Current State, Commands, and Key Files sections updated to reflect Phase 0 completion (per `execute.md`'s now-unconditional step)

## COMPLETION CHECKLIST
- [x] Tasks executed in order, each validated immediately
- [x] Full unit suite passes (49 tests)
- [x] Manual live-smoke run done and inspected (GOOGL end-to-end via `fetch_all`, cache-hit path verified: 7.8s cold, 0.16s warm)
- [x] Plan file updated with any deviations taken during implementation (below)

---

## EXECUTION DEVIATIONS (actual, as built)

1. **Stooq is blocked, not implemented.** `stooq.com`'s CSV endpoint now requires solving a
   JavaScript proof-of-work challenge — confirmed unreachable via `curl` (real browser
   User-Agent) and a markdown-conversion fetch tool. `data/stooq.py` is a documented stub
   (`NotImplementedError`); `PriceClient` wraps Tiingo only. User-approved deviation (Stooq is
   backfill fallback, not primary, per PRD §5) — not a Phase 0 blocker. See
   `free-data-sources.md` §3's correction.

2. **`FiscalPeriod` extended by 5 fields beyond the PRD's illustrative sketch**:
   `cost_of_revenue`, `sga_expense`, `current_assets`, `ppe_gross`, `total_debt`. Needed to
   compute all 8 Beneish M-Score components (the original 8-field sketch only supports 3:
   DSRI, SGI, TATA). User-approved. `total_debt`'s tag-alias resolution is a documented
   simplification (long-term debt only, when no combined long+short-term tag exists).

3. **`cash_conversion_cycle()` is a permanent coverage gap**, not a computed ratio —
   `FiscalPeriod` has no `accounts_payable` field (out of scope for the 5-field extension
   above), so the DPO leg of DSO+DIO−DPO can never resolve. Returns
   `RatioResult(value=None, reason="accounts_payable_not_in_fiscal_period_contract_dpo_uncomputable")`
   unconditionally. Flagged rather than silently approximated.

4. **Filing-section extraction (`data/filing_sections.py`) was added as new, unplanned scope.**
   The original plan named the Agent-or-Code decision and the `FilingSections` contract but
   never actually included a build task, file, or HTML-parsing dependency for it — a genuine
   gap in the plan, caught when building `fetch_all()`. User asked to close it out in this
   session rather than defer to Phase 2. Added `beautifulsoup4`/`lxml` as dependencies. The
   extraction heuristic (bold, non-hyperlinked "Item N." text distinguishes real section
   headers from Table-of-Contents entries and inline cross-references) was derived and
   validated against two real filers with different HTML conventions (Alphabet: ALL-CAPS
   body headers; Apple: mixed-case with CSS-driven visual capitalization) — see
   `data-layer.md` for the full writeup. Known limitation: filers whose headers aren't
   bold-styled will report a `CoverageGap`, not a wrong section.

5. **`fetch_all()` raises `TickerOutOfScope` rather than returning a
   `TickerIntakeResult | tuple[...]` union**, for consistency with this codebase's existing
   typed-exception pattern (`EdgarError`, `FredError`, `TiingoError`). Returns
   `list[MacroSeriesBundle]` (one per FRED series in a fixed list: `DGS10`, `FEDFUNDS`,
   `T10Y2Y`), not a single bundle — a memo needs more than one macro series.

6. **SIC exclusion ranges verified two ways**: live queries against SEC EDGAR's own
   `browse-edgar?SIC=...` endpoint for the codes with current registrants, cross-checked
   against the canonical SIC manual (OSHA's published Division H) for full major-group
   coverage. No codes were guessed from memory.

7. **FRED correction confirmed and applied**: `api_key` is required unconditionally (HTTP 400
   without one), not "works keyless at 30 req/min" as originally researched. Corrected in
   `free-data-sources.md` §2.

---

## NOTES

- **This plan is documentation only.** No files were created on disk as part of planning. Real API sample capture (for golden fixtures under `tests/golden/`) is explicitly deferred to `/execute` time, per this session's direction — planning should describe what needs to be captured, not capture it ahead of approval.
- **FRED correction**: `.agents/references/free-data-sources.md` states FRED works keyless at 30 req/min. A direct test today (`curl` against `/fred/series/observations` with no `api_key`) returned HTTP 400 `"Variable api_key is not set"` — the API appears to require a key unconditionally. The reference doc should get a correction pass; flagging here rather than silently editing it.
- **EDGAR shape confirmed live** (read-only checks performed this session, not persisted): Alphabet Inc. (CIK `0001652044`) successfully resolves `PaymentsToAcquirePropertyPlantAndEquipment`, `NetIncomeLoss`, and `RevenueFromContractWithCustomerExcludingAssessedTax` under `us-gaap`, matching the documented `companyconcept` schema (`cik, taxonomy, tag, label, description, entityName, units.USD[]` with `{start, end, val, accn, fy, fp, form, filed, frame}` per data point).
- **Recommend Alphabet (GOOGL, CIK `0001652044`) as the primary golden-fixture company** for this phase — it's already the running example for the two canonical Investigator eval cases planned in Phase 3 (benign vs. concerning capex-spike verdicts), so reusing it here gives continuity between the data layer's fixtures and the later agent evals rather than introducing an unrelated test company.
- Tiingo's documentation lists response fields (`date, open, high, low, close, volume, adjOpen/High/Low/Close/Volume, divCash, splitFactor`) but not a full example payload — a real sample requires a Tiingo free API key, which doesn't exist yet in this environment. Getting that key is a prerequisite for `/execute`'s Level 4 validation.
- Exact SIC code ranges for banks/insurers/REITs need verification against SEC's own SIC code list at `/execute` time — the plan names the general ranges but they should be confirmed, not assumed.

---

## Report

**Approach**: pure-code Phase 0, three independent API client modules unified behind typed contracts and a shared cache, plus deterministic ratio/valuation math and the SIC-exclusion intake gate — no LLM involvement anywhere.

**Plan file**: `.agents/plans/phase-0-data-layer.md`

**Complexity**: Medium-High — three external APIs with different auth/rate-limit shapes, plus the tag-alias and non-calendar-fiscal-year handling that the free-data-source research flagged as real gotchas, not edge cases.

**Key risks**:
1. FRED's actual auth requirement was documented incorrectly upstream (now corrected in this plan) — worth double-checking other provider assumptions live before building against them.
2. Tiingo/FRED key acquisition is a hard prerequisite for Level 4 validation and hasn't happened yet — should happen before `/execute` starts, not mid-implementation.
3. SIC code ranges for the exclusion list are stated but unverified — must be confirmed against SEC's authoritative list, not shipped from memory.

**Confidence for one-pass `/execute` success**: 7/10 — the contracts and task breakdown are concrete, but the three live-API integrations (especially exact Tiingo response shape and precise SIC ranges) carry real "documentation doesn't match reality" risk that unit tests against golden fixtures should catch early rather than late.
