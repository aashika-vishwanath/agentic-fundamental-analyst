# Feature: Phase 4 — Sector Analyst, Macro Sensitivity Analyst, Valuation Interpreter

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

## Feature Description

Three parallel, single-shot, Sonnet-tier narration agents (PRD §4 roster, PRD §12 Phase 4) that
turn already-computed deterministic context into the memo's relative-context sections:

- **Sector Analyst** — peer/segment positioning (feeds memo §3 Business Overview's segment angle
  and §6 Valuation's peer-comps cross-check).
- **Macro Sensitivity Analyst** — rate/macro backdrop framing (feeds memo §2 Investment Thesis'
  macro-backdrop reframe option and §8 Risks' macro risk framing).
- **Valuation Interpreter** — narrates a trailing DCF + peer comps with explicitly disclosed
  assumptions (feeds memo §6 Valuation, the one section the investment-memo-writing skill marks
  **INCLUDED, not deferred** — this is the load-bearing piece of this phase).

This phase also builds the deterministic work these three agents depend on and that doesn't exist
yet: SIC-based peer discovery + peer-financials assembly (new EDGAR data-layer work), trailing
free-cash-flow extraction from filed financials, and discount-rate/terminal-growth assumption
wiring — all in `valuation.py`/`edgar.py`, never inside an agent, per the "agents interpret,
deterministic code computes" hard constraint.

## User Story

As the builder running this system against a real ticker, I want the memo's Valuation section
grounded in a real trailing DCF and a real EDGAR-sourced peer comp set — with every assumption
(discount rate, terminal growth) disclosed as an assumption, not stated as fact — and the
Business Overview / Risks / Thesis sections given real peer and macro context, so the memo clears
the "good vs. boilerplate" bar the investment-memo-writing skill sets for these sections instead
of leaving them empty or fabricated.

## Problem / Solution Statement

**Problem**: Phases 0-3 give a complete earnings-quality read (ratios, filings, transcript,
anomaly investigation) but nothing that prices the company or contextualizes it against peers or
the macro backdrop. The skill doc marks Valuation's trailing DCF and self-built peer comps as
**INCLUDED**, not deferred — this can't be skipped, and the underlying math doesn't exist: no
peer-ticker discovery, no peer-financials fetch, no FCF-to-`dcf()` wiring, no discount-rate
sourcing.

**Approach chosen**: Build one deterministic peer-discovery pipeline (EDGAR SIC lookup →
cross-referenced against the ticker→CIK bulk file → per-candidate financials fetch →
`peer_multiples()`) that feeds **both** Sector Analyst and Valuation Interpreter from a single
computed `PeerCompsResult`, rather than having each agent (or worse, two separate deterministic
paths) discover peers independently. Sector Analyst narrates peer positioning; Valuation
Interpreter narrates the same comps as a valuation cross-check alongside DCF. This avoids paying
for peer discovery twice and avoids two disagreeing peer sets appearing in the same memo.

**Alternatives considered and rejected**:
- *Hand-curated static SIC→peer map* — rejected per discussion: doesn't scale past tickers
  manually added, and this system's whole design point is running constantly against arbitrary
  real tickers at zero marginal cost.
- *Forward-growth-projection DCF* (explicit revenue/margin forecast years) — rejected: the skill
  doc specifies **trailing/LTM DCF** ("price feed + filed cash flows + FRED risk-free rate"), not
  a growth model. `valuation.py::dcf()`'s existing `cash_flows: list[float]` input can be fed the
  last N years of *actual filed* FCF (`operating_cash_flow - capex` per annual `FiscalPeriod`)
  directly — no new forecasting model needed. This was the single biggest apparent gap going into
  planning and it closes for free once the terminology is read correctly.
- *Each Phase 4 agent doing its own Flag-candidate/promotion split* (Phase 1-3's pattern) —
  rejected: these agents don't raise Flags at all (PRD roster output types are
  `SectorContext`/`MacroContext`/`ValuationContext`, not `list[Flag]`). A new grounding mechanism
  is needed instead — see Data Contracts and the numeric-grounding section below.

## Feature Metadata

**Type**: New Capability
**Complexity**: High — the largest phase yet by surface area (3 new agents + new EDGAR
peer-discovery data layer + new valuation wiring + a 4th grounding mechanism + 3 eval datasets).
Consider executing Phase A (data layer) and validating it in isolation before starting Phase B
(agents) — each phase below has its own validation command for exactly this reason.
**Pipeline stage(s)**: The "parallel: Sector Analyst / Macro Sensitivity Analyst / Valuation
Interpreter" block (PRD §4 diagram, third parallel block, after the Investigator). Not wired into
`run_memo_pipeline()` yet — that's Phase 5; this phase produces standalone, individually callable,
individually eval'd stage functions, exactly like Phases 1-3 did before Phase 5 existed.
**Dependencies**: Phase 0 (`EdgarClient`, `FredClient`, `PriceClient`, `valuation.py`,
`contracts/macro.py`, `contracts/valuation.py`, `contracts/intake.py`), Phase 1's
`agents/models.py` convention. No dependency on Phases 2/3's Flag/grounding machinery — this phase
introduces a parallel, independent grounding mechanism.

## Agent-or-Code Decisions

| Component | Agent or Code | Why |
|---|---|---|
| SIC-based peer-ticker discovery | Code | Deterministic API call + parsing; no judgment call |
| Peer-financials assembly (`PeerFinancials` per candidate) | Code | XBRL concept lookups + arithmetic, same idiom as `get_financial_statement_bundle` |
| `peer_multiples()` (P/E, EV/Revenue, EV/EBITDA, medians) | Code | Already exists (Phase 0), pure arithmetic |
| Trailing FCF extraction from filed financials | Code | `operating_cash_flow - capex`, no judgment |
| `dcf()` bull/base/bear scenarios | Code | Already exists (Phase 0), pure arithmetic |
| Discount-rate assembly (FRED 10Y + fixed ERP) | Code | Arithmetic + a disclosed constant, not interpretation |
| Sector Analyst (peer/segment narrative) | Agent | Interpreting *what the numbers mean* for positioning is judgment |
| Macro Sensitivity Analyst (rate/macro narrative) | Agent | Interpreting regime relevance to this specific company is judgment |
| Valuation Interpreter (DCF + comps narrative) | Agent | Interpreting scenario spread / comp premium-or-discount is judgment |
| Numeric-grounding check on each agent's `summary` | Code | Deterministic verification, never an LLM judge (hard constraint) |

## Data Contracts

### `contracts/valuation.py` — additions (existing file; existing `DCFResult`/`DCFScenario`/
`PeerFinancials`/`PeerMultiples`/`PeerCompsResult` stay as-is, imported not redefined)

```python
from datetime import date  # new import
from agentic_fundamental_analyst.contracts.financials import CoverageGap  # new import


class ValuationAssumptions(BaseModel):
    risk_free_rate: float          # latest FRED DGS10 observation, as a decimal (e.g. 0.042)
    risk_free_rate_as_of: date     # that observation's date — for the Appendix citation
    equity_risk_premium: float     # fixed assumption constant — see Strategic Thinking below
    discount_rate: float           # risk_free_rate + equity_risk_premium
    terminal_growth: float         # fixed assumption constant


class ValuationResult(BaseModel):
    ticker: str
    assumptions: ValuationAssumptions
    dcf: DCFResult | None          # None if fewer than 2 usable trailing FCF periods
    comps: PeerCompsResult | None  # None if zero usable peers found — same object Sector Analyst got
    coverage_gaps: list[CoverageGap]
```

### `contracts/sector_analyst.py` — new file

```python
from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.valuation import PeerCompsResult, PeerFinancials


class SectorPeerData(BaseModel):
    ticker: str
    sic_code: str
    sic_description: str
    target: PeerFinancials
    peers: list[PeerFinancials]   # may be empty — see coverage_gaps
    comps: PeerCompsResult        # computed even from an empty/short peer list (medians -> None)
    coverage_gaps: list[CoverageGap]


class SectorAnalystOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
```

### `contracts/macro_analyst.py` — new file

```python
from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class CompanyMacroProfile(BaseModel):
    """Deliberately small — built from fields Phases 0-1 already fetch
    (TickerIntakeResult + FinancialStatementBundle), no new fetching."""

    ticker: str
    sic_description: str
    latest_revenue: float | None
    latest_total_debt: float | None
    revenue_cagr: float | None   # over the annual periods available; None if <2 periods


class MacroAnalystOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
```

### `contracts/valuation_interpreter.py` — new file

```python
from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class ValuationInterpreterOutput(BaseModel):
    ticker: str
    summary: str
    coverage_gaps: list[CoverageGap]
```

**Why no `AgentOutput`-vs-stage-`Output` split, unlike Phases 1-3**: that split exists because
Phase 1-3 agents propose *candidates* that get promoted-or-dropped against a closed table/quote.
These three agents produce no candidates — the agent's own `output_type` (a `summary: str` over an
already-fully-typed, already-computed input) *is* the returned type. Grounding is enforced by a
different mechanism (below), applied to the whole `summary` at once, not per-candidate.

### New grounding mechanism — `agents/numeric_grounding.py` (new file, mirrors `agents/grounding.py`)

The **fourth grounding mechanism** in this codebase, after closed-table lookup (Phase 1),
verbatim-quote checking (Phase 2), and URL provenance (Phase 3). None of those apply here because
these agents don't produce Flags — they narrate small, fully-typed numeric bundles (peer
multiples, macro series values, DCF scenario present values) directly into free text. Grounding
means: every number in `summary` must be traceable, within tolerance, to a real number in the
typed input, or a simple derived transform of two such numbers (a percent difference or ratio —
the natural vocabulary of a *comparative* narrative like "trades at a 22% discount to peer median
P/E").

```python
"""Numeric-value grounding — shared by the Sector, Macro Sensitivity, and Valuation Interpreter
agents (Phase 4). See module docstring rationale in the Phase 4 plan's Data Contracts section for
why this differs from agents/grounding.py's verbatim-quote check."""

import re
from itertools import combinations

_NUMBER_RE = re.compile(r"-?\d+\.?\d*")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        token = match.group()
        if _YEAR_RE.match(token):
            continue
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    return numbers


def expand_known_numbers(raw: set[float]) -> set[float]:
    """Raw values plus percent/rounded transforms (same tolerance idiom already
    prototyped in evals/financial_statements.py's _known_numbers) plus pairwise
    percent-differences and ratios between every pair of raw values."""
    known: set[float] = set()
    for v in raw:
        known.update({round(v, 4), round(v * 100, 4), round(v), round(v * 100)})
    for a, b in combinations(raw, 2):
        if b:
            known.add(round((a - b) / b * 100, 4))
            known.add(round(a / b, 4))
        if a:
            known.add(round((b - a) / a * 100, 4))
            known.add(round(b / a, 4))
    return known | raw


def is_grounded(x: float, known: set[float]) -> bool:
    tolerance = max(0.5, 0.01 * abs(x))
    return any(abs(x - k) <= tolerance for k in known)


def summary_is_grounded(summary: str, known_raw: set[float]) -> bool:
    """Hard gate — promoted from Phase 1's informational-only version to a real
    gate, since these agents have no other grounding structure. Empty number
    list is vacuously grounded (a purely qualitative summary is valid)."""
    numbers = extract_numbers(summary)
    if not numbers:
        return True
    known = expand_known_numbers(known_raw)
    return all(is_grounded(x, known) for x in numbers)
```

Each agent module supplies its own `known_raw: set[float]` collector from its typed input (e.g.
`_known_numbers_from_valuation(result: ValuationResult) -> set[float]`) — same "shared check,
per-agent source resolution" split `evals/grounding.py`'s docstring already documents for the
quote-grounding mechanism.

**Runtime enforcement (not just eval-time)**: each `run_sector_analyst()`/`run_macro_analyst()`/
`run_valuation_interpreter()` calls `summary_is_grounded()` after the agent call, mirroring Phase
1-3's "grounding is enforced by code, not just checked after the fact." Unlike Phase 1-3 there is
no candidate to drop — the whole `summary` is prose. On failure: replace `summary` with a fixed
deterministic fallback string and append a `CoverageGap(field="summary",
reason="numeric_grounding_check_failed")`, never ship unverified prose. **No retry** — matches
Phase 1-3's "drop, don't trust" idiom rather than adding new resilience machinery; flagged as a
real tradeoff in NOTES (a coarser failure mode than Phase 1-3's per-candidate drop, since the
whole narrative is lost on one bad number, not just the offending claim).

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing

- `src/agentic_fundamental_analyst/agents/financial_statements.py` — mirror this agent's overall
  shape (Agent definition, `logfire.span` stage wrapper, docstring style) even though the
  candidate/grounding split doesn't apply here.
- `src/agentic_fundamental_analyst/agents/filings.py` (lines 77-160) — the `run_X_analyst(ticker,
  ...)` signature pattern for an input type with no ticker field of its own.
- `src/agentic_fundamental_analyst/agents/grounding.py` — the shared-check-module pattern to
  mirror exactly for `agents/numeric_grounding.py`.
- `evals/financial_statements.py` (lines 131-231, esp. `_known_numbers`/`_is_grounded`/
  `_summary_numeric_grounding_ratio`) — this is the *exact* idiom `numeric_grounding.py`
  generalizes from informational to a hard gate; read before writing the new module so the
  tolerance logic isn't reinvented differently.
- `src/agentic_fundamental_analyst/data/edgar.py` (lines 150-260, 449-480) — `_fetch_company_tickers`,
  `resolve_concept`, `get_ticker_intake`, `_zero_pad_cik` — the exact helpers/idioms the new peer-
  discovery methods reuse. Also read the module's cache-decorator pattern (`@cached("source",
  timedelta(days=N))`) used on every other `_fetch_*` helper.
- `src/agentic_fundamental_analyst/data/tag_aliases.py` — where the new `cash_and_equivalents`
  alias list is added; note the existing `total_debt` comment about tag imprecision (same caveat
  applies when this list is reused for peer companies).
- `src/agentic_fundamental_analyst/valuation.py` — `dcf()`, `peer_multiples()`, `_median_ignoring_none`
  — reused as-is, not reimplemented. New code (`trailing_free_cash_flows`,
  `build_valuation_assumptions`) goes in this same module, same style.
- `src/agentic_fundamental_analyst/ratios.py` (lines 318-329, `compute_trend_bundle`) — the
  `form == "10-K"` / sorted-by-`period_end` annual-period filter to mirror exactly in
  `trailing_free_cash_flows()`.
- `.agents/references/data-layer.md` — read in full; this plan's data-layer additions get a new
  section appended here at completion (see Acceptance Criteria).
- `.claude/skills/investment-memo-writing/SKILL.md` §1, sections 2/3/6/8 — the exact "good vs.
  boilerplate" bar each agent's prompt must be written against; Section 6 in particular is the
  literal source of the "trailing DCF... discount rate explicitly sourced... stated as an
  assumption not a fact" requirement this phase implements.
- `tests/unit/test_financial_statements_agent.py` — the `TestModel(custom_output_args=...)`
  plumbing-test pattern to mirror for all three new agents.
- `tests/unit/test_edgar_client.py` (imports/fixture-loading pattern) — the `respx.mock` +
  `GOLDEN` fixture-loading pattern for the new peer-discovery EdgarClient tests.

### New files to create

- `src/agentic_fundamental_analyst/contracts/sector_analyst.py` — `SectorPeerData`, `SectorAnalystOutput`
- `src/agentic_fundamental_analyst/contracts/macro_analyst.py` — `CompanyMacroProfile`, `MacroAnalystOutput`
- `src/agentic_fundamental_analyst/contracts/valuation_interpreter.py` — `ValuationInterpreterOutput`
- `src/agentic_fundamental_analyst/agents/numeric_grounding.py` — shared grounding check (above)
- `src/agentic_fundamental_analyst/agents/sector.py` — `sector_analyst`, `run_sector_analyst()`
- `src/agentic_fundamental_analyst/agents/macro.py` — `macro_sensitivity_analyst`, `run_macro_sensitivity_analyst()`
- `src/agentic_fundamental_analyst/agents/valuation_interpreter.py` — `valuation_interpreter`, `run_valuation_interpreter()`
- `src/agentic_fundamental_analyst/data/sic_lookup.py` — pure XML-parsing function(s) for the SIC
  browse-edgar atom feed, mirroring `filing_sections.py`'s role as a standalone parsing module
  network-testable in isolation
- `evals/sector_analyst.py`, `evals/macro_analyst.py`, `evals/valuation_interpreter.py`
- `tests/unit/test_sector_agent.py`, `tests/unit/test_macro_agent.py`, `tests/unit/test_valuation_interpreter_agent.py`
- `tests/unit/test_sic_lookup.py`, `tests/unit/test_peer_discovery.py` (new `EdgarClient` methods)
- `tests/unit/test_valuation_trailing_fcf.py` (or extend `tests/unit/test_valuation.py`)
- `tests/golden/sic7370_browse_edgar_sample.xml` — **already captured this session**, real live
  SEC EDGAR response (SIC=7370, GOOGL's own SIC code), trimmed to 3 entries + the real pagination
  footer. Confirms the endpoint's `name`/`title` fields are unusable (`"ARRAY(0x...)"` — a
  PHP/Perl array-to-string bug on SEC's legacy CGI page) and that `<cik>` is the only reliable
  per-entry field; parsing must use the `company_tickers.json` reverse index for ticker/name, not
  this feed.
- `tests/golden/googl_shares_outstanding_concept.json` — **already captured this session**, real
  trimmed `us-gaap:CommonStockSharesOutstanding` companyconcept payload for GOOGL (CIK
  0001652044), same shape/style as the existing `googl_revenue_concept.json` fixture. Confirms
  this tag resolves cleanly to a single combined ~12B-share figure for GOOGL despite its multiple
  share classes (no per-class dimensional handling needed).

### Documentation to READ before implementing

- Installed Pydantic AI skill — confirm no capability changes needed (these three agents use no
  new pydantic-ai features beyond what Phases 1-2 already established: `Agent`, `instructions=`,
  `output_type=`, `.run()`).
- No new external API docs needed beyond what's captured below — SEC EDGAR's `browse-edgar`
  SIC-lookup endpoint and `companyconcept` shares-outstanding tag were both verified live this
  session (see Research Findings below), not from secondary sources.

### Patterns to follow

**Agent definition + stage wrapper** (mirror `agents/financial_statements.py:73-161`, adapted —
no candidate/grounding-drop step, just the numeric-grounding gate):

```python
sector_analyst = Agent(
    SECTOR_ANALYST_MODEL,
    name="sector_analyst",
    output_type=SectorAnalystOutput,
    instructions=_INSTRUCTIONS,
)


async def run_sector_analyst(peer_data: SectorPeerData) -> SectorAnalystOutput:
    with logfire.span(
        "sector_analyst_stage", ticker=peer_data.ticker, sic_code=peer_data.sic_code
    ) as span:
        result = await sector_analyst.run(peer_data.model_dump_json(indent=2))
        agent_output = result.output
        known = _known_numbers_from_sector(peer_data)
        grounded = summary_is_grounded(agent_output.summary, known)
        span.set_attribute("peer_count", len(peer_data.peers))
        span.set_attribute("grounding_passed", grounded)
    if not grounded:
        return SectorAnalystOutput(
            ticker=peer_data.ticker,
            summary=_UNGROUNDED_FALLBACK_SUMMARY,
            coverage_gaps=[
                *peer_data.coverage_gaps,
                CoverageGap(field="summary", reason="numeric_grounding_check_failed"),
            ],
        )
    return SectorAnalystOutput(
        ticker=peer_data.ticker, summary=agent_output.summary, coverage_gaps=peer_data.coverage_gaps
    )
```

**Model-tier constants** (append to `agents/models.py`, same one-constant-per-agent convention as
the existing four):

```python
SECTOR_ANALYST_MODEL = "anthropic:claude-sonnet-5"
MACRO_SENSITIVITY_ANALYST_MODEL = "anthropic:claude-sonnet-5"
VALUATION_INTERPRETER_MODEL = "anthropic:claude-sonnet-5"
```

**Trailing FCF extraction** (`valuation.py`, mirrors `ratios.py:318-329`'s exact filter):

```python
def trailing_free_cash_flows(bundle: FinancialStatementBundle) -> list[float] | None:
    """Last N annual (10-K) periods' operating_cash_flow - capex, oldest first —
    the 'filed cash flows' the trailing DCF discounts as if they were the next
    N years' cash flows (see Problem/Solution: no growth-projection model)."""
    annual = sorted((p for p in bundle.periods if p.form == "10-K"), key=lambda p: p.period_end)
    flows = [
        p.operating_cash_flow - p.capex
        for p in annual
        if p.operating_cash_flow is not None and p.capex is not None
    ]
    return flows if len(flows) >= 2 else None
```

---

## IMPLEMENTATION PLAN

### Phase A: Data & Contracts

1. Add `cash_and_equivalents` to `TAG_ALIASES` (`data/tag_aliases.py`):
   `["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]`.
2. `data/sic_lookup.py` — `parse_sic_atom_feed(xml_text: str) -> list[str]`: extract every
   `<cik>` value inside an `<entry>`, zero-padded to 10 digits. Ignore `title`/`name` entirely
   (confirmed broken — see golden fixture). Pure function, tested against
   `tests/golden/sic7370_browse_edgar_sample.xml` with no network.
3. `data/edgar.py` additions:
   - `_fetch_sic_company_list(sic_code: str, count: int) -> str` — cached 7 days, GET
     `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC={sic_code}&type=10-K&dateb=&owner=include&count={count}&output=atom`,
     return raw text (not JSON — reuse `_get_text`, not `_get_json`).
   - `EdgarClient.peers_by_sic(sic_code: str, exclude_cik: str, limit: int = 100) -> list[tuple[str, str]]`
     — fetch one page (`count=100`, no pagination — see NOTES), parse CIKs via
     `parse_sic_atom_feed`, cross-reference each against `_fetch_company_tickers()`'s data (build
     a `{cik10: ticker}` reverse index from its `cik_str`/`ticker` fields), drop `exclude_cik` and
     any CIK with no ticker match, return up to `limit` `(cik10, ticker)` pairs in feed order.
   - `EdgarClient._latest_annual_concept_value(cik10: str, concept: str) -> float | None` — reuse
     `resolve_concept()`; for duration concepts (`revenue`, `net_income`) filter to `form ==
     "10-K"` and the existing `_ANNUAL_DURATION_DAYS_RANGE`, take the most recent `end`; for
     instant concepts (`total_debt`, `cash_and_equivalents`) take the most recent `end` regardless
     of form.
   - `EdgarClient.latest_shares_outstanding(cik10: str) -> float | None` — `resolve_concept(cik10,
     "shares_outstanding")` is **not** the path (that concept isn't in `TAG_ALIASES` — deliberately
     kept out of `FiscalPeriod`/`get_financial_statement_bundle`'s blast radius, see
     Problem/Solution). Call `company_concept(cik10, "CommonStockSharesOutstanding")` directly,
     take the most recent point in the `"shares"` unit array.
   - `EdgarClient.build_peer_financials(ticker: str, cik10: str, price: float) -> PeerFinancials | None`
     — assembles revenue/net_income/total_debt/cash_and_equivalents via
     `_latest_annual_concept_value`, shares via `latest_shares_outstanding`. `ebitda` is always
     `None` (no reliable generic-peer EBITDA source — no operating-income/interest/tax fields
     fetched for arbitrary peers; `PeerMultiples.ev_to_ebitda` already degrades to `None`
     gracefully). Returns `None` only if `price` or `shares_outstanding` can't be resolved (both
     are non-`Optional` fields on `PeerFinancials`) — a candidate that can't produce those two is
     excluded from the peer set entirely, never included with a fabricated number.
4. `data/fetch.py` — `fetch_all()` becomes a **6-tuple**: prepend `TickerIntakeResult` (already
   computed internally at line "intake = await edgar.get_ticker_intake(ticker)" — just stop
   discarding it). Update the one existing call site
   (`tests/unit/test_fetch_all.py:92`) and CLAUDE.md's documented Commands snippet.
5. `valuation.py` additions:
   - `trailing_free_cash_flows()` — see Patterns above.
   - `_EQUITY_RISK_PREMIUM = 0.055`, `_TERMINAL_GROWTH_ASSUMPTION = 0.025` — module-level
     constants with a docstring citing them as disclosed assumptions (see Strategic Thinking for
     the numeric rationale), not fetched from any source (none exists free).
   - `build_valuation_assumptions(macro_bundles: list[MacroSeriesBundle]) -> ValuationAssumptions | None`
     — finds the `DGS10` bundle, takes its most recent non-`None` point, returns `None` (full
     coverage gap) if `DGS10` is missing or entirely `None`-valued.
6. Peer-discovery orchestration (new function, `data/edgar.py` or a small new
   `data/peer_discovery.py` — decide during implementation based on which keeps `EdgarClient`'s
   existing size/shape more consistent): `discover_sector_peers(ticker, cik10, sic_code,
   sic_description, target_price) -> SectorPeerData`. Tries candidates from `peers_by_sic()` in
   order, `asyncio.gather`-fetching `build_peer_financials()` for a batch at a time, stopping once
   `_TARGET_PEER_COUNT = 5` succeed or `_MAX_PEER_CANDIDATES_TRIED = 15` have been attempted.
   Builds the target's own `PeerFinancials` the same way. Calls `peer_multiples()` (existing,
   Phase 0) on whatever was assembled. If fewer than `_MIN_PEER_COUNT_FOR_COMPS = 2` peers found,
   appends a `CoverageGap(field="peers", reason=f"insufficient peer data for SIC {sic_code}: found
   {n}, needed >= {_MIN_PEER_COUNT_FOR_COMPS}")` — the comps object is still returned (medians
   just resolve to `None` with 0-1 peers via the existing `_median_ignoring_none`), never crashes.

**Phase A validation**: `uv run pytest tests/unit/test_sic_lookup.py
tests/unit/test_peer_discovery.py tests/unit/test_valuation.py tests/unit/test_fetch_all.py -q`
— all network-free (respx-mocked against the two new golden fixtures plus existing ones).

### Phase B: Core Implementation (the three agents)

Each agent: `_INSTRUCTIONS` constant (task list style, matching `financial_statements.py`/
`filings.py`), `Agent(...)` definition, `run_X(...)` stage wrapper per the Patterns section.

- **Sector Analyst instructions** — task: (1) write a 2-4 sentence summary comparing the target's
  P/E, EV/Revenue, EV/EBITDA to the peer medians in `comps`, specific to real numbers, never
  generic ("well-positioned in a growing sector"); (2) explicitly state when the peer set is thin
  (`len(peers) < 2`) and qualify confidence accordingly rather than treating a 1-peer median as a
  real benchmark; (3) zero notable peer-relative observations is a valid outcome if the target
  sits squarely at peer medians — don't manufacture a differentiator.
- **Macro Sensitivity Analyst instructions** — task: (1) 2-4 sentence summary of the current rate/
  macro regime (`DGS10`, `FEDFUNDS`, `T10Y2Y` levels and recent direction) and *why it's relevant
  to this specific company's profile* (`CompanyMacroProfile` — leverage exposure via
  `latest_total_debt`, growth-vs-rate sensitivity via `revenue_cagr`) — never generic "rates
  matter to all companies" boilerplate; (2) a null/flat regime with no notable company-specific
  sensitivity is a valid, expected output — don't invent drama.
- **Valuation Interpreter instructions** — task: (1) summarize the DCF bull/base/bear present
  values, explicitly stating the discount rate and terminal growth **as disclosed assumptions**
  ("assuming a discount rate of X%, derived from the FRED 10Y yield of Y% plus an assumed Z%
  equity risk premium..."), never as fact; (2) cross-check against `comps` the same way Sector
  Analyst does; (3) if `dcf` is `None` (fewer than 2 trailing FCF periods) or `comps` is `None`
  (no peers found), say so plainly and rely on whichever method is available — never fabricate the
  missing one.

**Phase B validation**: `uv run pytest tests/unit/test_sector_agent.py
tests/unit/test_macro_agent.py tests/unit/test_valuation_interpreter_agent.py -q` (TestModel
plumbing, zero API spend) — mirror
`test_financial_statements_agent.py`'s `test_agent_default_test_model_produces_valid_output_type`
plus a scripted-output test proving the numeric-grounding fallback actually fires on a fabricated
number.

### Phase C: Integration (Logfire + cost/latency observability)

- Spans: `sector_analyst_stage` (`ticker`, `sic_code`, `peer_count`, `grounding_passed`),
  `macro_sensitivity_analyst_stage` (`ticker`, `grounding_passed`), `valuation_interpreter_stage`
  (`ticker`, `dcf_available`, `comps_available`, `grounding_passed`) — all per the Patterns
  snippet above.
- New deterministic-stage span: `peer_discovery_stage` (`ticker`, `sic_code`,
  `candidates_scanned`, `peers_found`) wrapping `discover_sector_peers()` — per CLAUDE.md's
  Observability convention that *every* pipeline stage, agent or deterministic, gets cost/signal
  attributes, and because this is the phase's real latency risk (see Strategic Thinking).
- No pipeline wiring yet (`pipeline.py` is Phase 5) — these three stage functions remain
  independently callable, same as Phases 1-3 were before Phase 5 existed.

### Phase D: Evals & Validation

Three new datasets, `evals/sector_analyst.py` / `evals/macro_analyst.py` /
`evals/valuation_interpreter.py`, same structure as `evals/financial_statements.py`.

---

## STEP-BY-STEP TASKS

### ADD `cash_and_equivalents` to `src/agentic_fundamental_analyst/data/tag_aliases.py`
- **IMPLEMENT**: new dict key with the two-alias list above.
- **PATTERN**: `tag_aliases.py`'s existing `total_debt` entry (same imprecision-caveat comment style).
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/data/tag_aliases.py`

### CREATE `src/agentic_fundamental_analyst/data/sic_lookup.py`
- **IMPLEMENT**: `parse_sic_atom_feed(xml_text: str) -> list[str]` using `lxml`/`bs4` (already a
  dependency), `xml` parser mode. Extract every `<cik>` text node inside an `<entry>`.
- **GOTCHA**: the feed's `name`/`title` attributes are `"ARRAY(0x...)"` garbage — do not parse
  them for anything. `<entry>` count on one page maxes at the requested `count` param (verified
  live: `count=40` returned exactly 40 entries, `count=100` untested but documented SEC convention
  — confirm the real cap during implementation with one more live call before hardcoding `count=100`).
- **VALIDATE**: `uv run pytest tests/unit/test_sic_lookup.py -q`

### CREATE `tests/unit/test_sic_lookup.py`
- **IMPLEMENT**: load `tests/golden/sic7370_browse_edgar_sample.xml`, assert `parse_sic_atom_feed`
  returns exactly the 3 real CIKs in the fixture (`0001595326`, `0001730732`, `0001525494`),
  zero-padded, in document order.
- **VALIDATE**: `uv run pytest tests/unit/test_sic_lookup.py -q`

### UPDATE `src/agentic_fundamental_analyst/data/edgar.py`
- **IMPLEMENT**: `_fetch_sic_company_list`, `EdgarClient.peers_by_sic`,
  `EdgarClient._latest_annual_concept_value`, `EdgarClient.latest_shares_outstanding`,
  `EdgarClient.build_peer_financials` — see Phase A §3 above for exact signatures/behavior.
- **PATTERN**: `edgar.py:160-200` (`@cached` decorator usage on `_fetch_*` helpers),
  `edgar.py:233-241` (`resolve_concept`).
- **IMPORTS**: `from agentic_fundamental_analyst.data.sic_lookup import parse_sic_atom_feed`
- **GOTCHA**: `_fetch_company_tickers()`'s reverse index must be built once per call (values keyed
  by arbitrary string index, not CIK — iterate `.values()`, key by zero-padded `cik_str`).
- **VALIDATE**: `uv run pytest tests/unit/test_peer_discovery.py -q`

### CREATE `tests/unit/test_peer_discovery.py`
- **IMPLEMENT**: respx-mock the SIC atom feed (golden fixture) + `company_tickers_sample.json` +
  per-candidate `companyconcept` responses (mock at least one candidate resolving fully, one
  missing a required field so it's excluded). Assert `peers_by_sic` excludes the target's own CIK
  and any CIK absent from the ticker index; assert `build_peer_financials` returns `None` when
  price/shares can't resolve.
- **PATTERN**: `tests/unit/test_edgar_client.py`'s `respx.mock` + `GOLDEN` fixture-loading pattern.
- **VALIDATE**: `uv run pytest tests/unit/test_peer_discovery.py -q`

### UPDATE `src/agentic_fundamental_analyst/data/fetch.py`
- **IMPLEMENT**: return `TickerIntakeResult` as the first element of a 6-tuple (don't discard
  `intake` after the exclusion check).
- **VALIDATE**: `uv run pytest tests/unit/test_fetch_all.py -q` (after updating its one call site)

### UPDATE `tests/unit/test_fetch_all.py`
- **IMPLEMENT**: `intake, financials, filings, macro, prices, transcript = await fetch_all("GOOGL")`
  at line 92; add an assertion on `intake.sic_code`/`intake.in_scope`.
- **VALIDATE**: `uv run pytest tests/unit/test_fetch_all.py -q`

### UPDATE `src/agentic_fundamental_analyst/valuation.py`
- **IMPLEMENT**: `trailing_free_cash_flows`, `_EQUITY_RISK_PREMIUM`, `_TERMINAL_GROWTH_ASSUMPTION`,
  `build_valuation_assumptions` — see Phase A §5 and Patterns above.
- **IMPORTS**: `from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle`,
  `from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle`,
  `from agentic_fundamental_analyst.contracts.valuation import ValuationAssumptions`
- **VALIDATE**: `uv run pytest tests/unit/test_valuation.py -q`

### CREATE peer-discovery orchestration (`discover_sector_peers`)
- **IMPLEMENT**: see Phase A §6. Decide file placement (edgar.py vs. new
  `data/peer_discovery.py`) based on keeping each module's responsibility clean — this function
  calls both `EdgarClient` methods and `valuation.peer_multiples()`, so it's a cross-cutting
  orchestrator, not pure EDGAR access; leaning toward a new `data/peer_discovery.py` for that
  reason, confirm during implementation.
- **VALIDATE**: `uv run pytest tests/unit/test_peer_discovery.py -q`

### CREATE `src/agentic_fundamental_analyst/contracts/sector_analyst.py`, `contracts/macro_analyst.py`, `contracts/valuation_interpreter.py`
- **IMPLEMENT**: exact models from Data Contracts above.
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/contracts`

### CREATE `src/agentic_fundamental_analyst/agents/numeric_grounding.py`
- **IMPLEMENT**: exact module from Data Contracts above.
- **VALIDATE**: `uv run pytest tests/unit/test_numeric_grounding.py -q` (new small unit test:
  assert a real number grounds, a fabricated one doesn't, a percent-difference between two known
  numbers grounds, a year token is never treated as a number to ground)

### CREATE `src/agentic_fundamental_analyst/agents/sector.py`, `agents/macro.py`, `agents/valuation_interpreter.py`
- **IMPLEMENT**: per Phase B above and the Patterns snippet.
- **PATTERN**: `agents/financial_statements.py` (overall shape), `agents/filings.py:142-160` (stage
  wrapper taking a non-self-identifying-ticker input... N/A here, all three new input types do
  carry `ticker`, mirror `financial_statements.py`'s simpler `run_X(bundle)` signature instead).
- **VALIDATE**: `uv run pytest tests/unit/test_sector_agent.py tests/unit/test_macro_agent.py tests/unit/test_valuation_interpreter_agent.py -q`

### CREATE the three new unit test files (plumbing)
- **IMPLEMENT**: mirror `tests/unit/test_financial_statements_agent.py`'s
  `test_agent_default_test_model_produces_valid_output_type` plus one scripted-`TestModel` test
  per agent proving a fabricated number in `summary` triggers the fallback path (`coverage_gaps`
  contains `numeric_grounding_check_failed`).
- **VALIDATE**: `uv run pytest tests/unit/test_sector_agent.py tests/unit/test_macro_agent.py tests/unit/test_valuation_interpreter_agent.py -q`

### CREATE `evals/sector_analyst.py`, `evals/macro_analyst.py`, `evals/valuation_interpreter.py`
- **IMPLEMENT**: see Testing Strategy below for cases/evaluators.
- **PATTERN**: `evals/financial_statements.py` end to end (dataset structure, `if __name__ ==
  "__main__"` runner, `LLMJudge(model=<agent's own model constant>)`).
- **VALIDATE**: `ANTHROPIC_API_KEY=<key> uv run python -m evals.sector_analyst` (and the other two) — real spend

### UPDATE `.agents/references/agents.md`
- **IMPLEMENT**: append a "Sector Analyst / Macro Sensitivity Analyst / Valuation Interpreter
  (Phase 4)" section documenting the numeric-grounding mechanism (4th mechanism), the shared
  peer-discovery design, and real cost/latency numbers once live-verified. Remove these three from
  the "Not yet built (Phase 4+)" list at the bottom.

### UPDATE `.agents/references/data-layer.md`
- **IMPLEMENT**: append a "Phase 4: SIC-based peer discovery" section documenting the
  `browse-edgar` atom-feed gotcha (broken name/title fields), the `fetch_all()` 6-tuple change,
  and the new `cash_and_equivalents`/shares-outstanding lookups.

### UPDATE `CLAUDE.md`
- **IMPLEMENT**: Current State section — mark Phase 4 complete, update the Layout listing (new
  `contracts/`/`agents/`/`data/` files), update the `fetch_all()` Commands snippet to the 6-tuple,
  add real cost/latency observations from live validation. Mandatory per the project's own
  "must update at the end of every phase" rule.
- **VALIDATE**: re-read against `git log`/`git status` for staleness, per this project's own `/prime` convention.

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe)

- `test_sic_lookup.py` — pure XML parsing against the real golden fixture (no network).
- `test_peer_discovery.py` — respx-mocked `EdgarClient` peer methods against golden fixtures
  (`sic7370_browse_edgar_sample.xml`, `company_tickers_sample.json`, plus mocked companyconcept
  responses for candidate revenue/net_income/total_debt/cash/shares).
- `test_valuation.py` additions — `trailing_free_cash_flows()` against a hand-built
  `FinancialStatementBundle` (annual-only filter correctness, `<2`-period → `None`),
  `build_valuation_assumptions()` against a `MacroSeriesBundle` fixture (missing DGS10 → `None`).
- `test_numeric_grounding.py` — the extract/expand/is_grounded/summary_is_grounded functions in
  isolation.
- `test_sector_agent.py` / `test_macro_agent.py` / `test_valuation_interpreter_agent.py` —
  `TestModel` plumbing (valid output type) + scripted-output grounding-fallback tests, same shape
  as `test_financial_statements_agent.py`.
- `test_fetch_all.py` — updated for the 6-tuple.

### Eval datasets (Pydantic Evals)

**`evals/sector_analyst.py`** — Cases: `premium_to_peer_median` (target's P/E well above peer
median), `discount_to_peer_median` (well below), `at_peer_median_no_notable_signal` (clean/
negative case — the over-flagging guard analog: summary should NOT manufacture a differentiator),
`thin_peer_set_coverage_gap` (0-1 peers — `coverage_gaps` must carry the insufficiency note,
summary must qualify confidence). Evaluators, in preference order: (1) deterministic —
`SectorGroundingEvaluator` using `summary_is_grounded` against `SectorPeerData`'s real numbers,
hard gate; (2) recall — `ExpectedCoverageGapPresent` for the thin-peer case; (3) `LLMJudge` — "the
summary is a specific comparison to real peer multiples, not generic sector commentary that could
describe any company in this SIC code," pinned to `SECTOR_ANALYST_MODEL`.

**`evals/macro_analyst.py`** — Cases: `rising_rate_regime`, `easing_regime`,
`flat_stable_regime_no_drama` (clean case), `dgs10_missing_coverage_gap` (all-`None` DGS10 points
— agent must not fabricate a rate). Evaluators: (1) `MacroGroundingEvaluator` (hard gate); (2)
`LLMJudge` — "the summary ties the macro regime to this specific company's profile
(`CompanyMacroProfile`), not generic 'rates matter to all companies' commentary," pinned to
`MACRO_SENSITIVITY_ANALYST_MODEL`.

**`evals/valuation_interpreter.py`** — Cases: `dcf_and_comps_both_available_premium_valuation`,
`bear_scenario_undefined_present_value` (discount_rate <= terminal_growth in the bear leg —
`present_value=None` — summary must handle gracefully, never invent a number), `comps_unavailable_dcf_only`
(`comps=None`), `dcf_unavailable_comps_only` (`dcf=None`, <2 trailing FCF periods), `both_unavailable_pure_coverage_gap`.
Evaluators: (1) `ValuationGroundingEvaluator` (hard gate, includes `assumptions.discount_rate`/
`terminal_growth`/`risk_free_rate` in the known-number set); (2) recall — `ExpectedCoverageGapPresent`
for the `_unavailable` cases; (3) `LLMJudge` — "the discount rate and terminal growth are stated
explicitly as assumptions (e.g. 'assuming...', 'an assumed...'), never as fact — this is the
skill doc's Section 6 requirement verbatim," pinned to `VALUATION_INTERPRETER_MODEL`.

**Trajectory evals**: N/A — none of these three agents use tools.

### Edge cases

- Target ticker's SIC code has zero other traded-ticker filers on the first page of the
  `browse-edgar` feed (rare but possible for an unusual SIC) → `SectorPeerData.peers == []`,
  `comps` medians all `None`, coverage gap present, both agents narrate qualitatively.
- FRED `DGS10` bundle present but every point is `None` (upstream FRED outage) →
  `build_valuation_assumptions` returns `None` → `ValuationResult` needs its own top-level
  handling (assumptions can't be `None` per the contract — decide during implementation whether
  `ValuationResult.assumptions` should become `Optional` too, or whether a missing risk-free rate
  should hard-fail the whole valuation stage with an explicit `CoverageGap` and no `ValuationResult`
  at all; leaning toward the latter, since a DCF genuinely cannot proceed without a discount rate —
  confirm during implementation and update this plan's Data Contracts if `assumptions` becomes Optional).
- Company with exactly 1 annual (10-K) period on file (recent IPO) → `trailing_free_cash_flows`
  returns `None` (the `<2`-period guard) → `ValuationResult.dcf is None`, comps-only valuation.
- A peer candidate resolves financials but its `total_debt`/`cash_and_equivalents` don't (tag
  alias miss) → `PeerFinancials` still constructed (those fields are `Optional`), `ev_to_revenue`/
  `ev_to_ebitda` degrade to `None` for that peer via the existing `_enterprise_value` guard — never
  excluded from the peer list on this basis alone (only `price`/`shares_outstanding` gaps exclude
  a candidate).

---

## VALIDATION COMMANDS

### Level 1: Syntax & style
```
uv run ruff check .
uv run pyright src tests evals
```

### Level 2: Unit tests
```
uv run pytest tests/unit -q
```
Zero regressions on the existing 111 tests; new tests for this phase pass alongside them.

### Level 3: Evals
```
ANTHROPIC_API_KEY=<key> uv run python -m evals.sector_analyst
ANTHROPIC_API_KEY=<key> uv run python -m evals.macro_analyst
ANTHROPIC_API_KEY=<key> uv run python -m evals.valuation_interpreter
```
Passing bar: each dataset's grounding evaluator at **100%** (hard gate, no exceptions); recall
evaluators pass on every case including the clean/coverage-gap ones; `LLMJudge` passes on at least
5/6 cases per dataset (softest bar — never loosen a rubric to force a pass, flag it instead, same
rule as every prior phase).

### Level 4: Manual (live)
Run each new stage function against a real ticker (GOOGL, per this project's established
convention) and inspect the Logfire trace:
```python
import asyncio
from agentic_fundamental_analyst.data.fetch import fetch_all
from agentic_fundamental_analyst.data.peer_discovery import discover_sector_peers  # or wherever placed
from agentic_fundamental_analyst.agents.sector import run_sector_analyst
from agentic_fundamental_analyst.agents.macro import run_macro_sensitivity_analyst
from agentic_fundamental_analyst.agents.valuation_interpreter import run_valuation_interpreter
from agentic_fundamental_analyst.valuation import trailing_free_cash_flows, build_valuation_assumptions, dcf
from agentic_fundamental_analyst.contracts.valuation import ValuationResult

async def main():
    intake, financials, filings, macro, prices, transcript = await fetch_all("GOOGL")
    latest_price = prices.bars[-1].close  # confirm real field name during implementation
    peer_data = await discover_sector_peers(
        "GOOGL", intake.cik, intake.sic_code, intake.sic_description, latest_price
    )
    sector_out = await run_sector_analyst(peer_data)
    assumptions = build_valuation_assumptions(macro)
    flows = trailing_free_cash_flows(financials)
    dcf_result = dcf(flows, assumptions.discount_rate, assumptions.terminal_growth) if flows else None
    valuation_result = ValuationResult(
        ticker="GOOGL", assumptions=assumptions, dcf=dcf_result, comps=peer_data.comps,
        coverage_gaps=peer_data.coverage_gaps,
    )
    valuation_out = await run_valuation_interpreter(valuation_result)
    print(sector_out.summary, valuation_out.summary)

asyncio.run(main())
```
Expected Logfire spans: `peer_discovery_stage`, `sector_analyst_stage`, `macro_sensitivity_analyst_stage`,
`valuation_interpreter_stage`, each with the attributes listed in Phase C, `grounding_passed=true`
on a healthy run, and `peer_discovery_stage.peers_found >= 2`.

### Level 5: Full-pipeline smoke run
N/A this phase — `run_memo_pipeline` doesn't exist until Phase 5. Level 4's manual script is the
closest available integration check.

---

## ACCEPTANCE CRITERIA

- [ ] Contracts match this plan exactly (or documented deviations, same as every prior phase's
  Execution Deviations convention); no untyped boundaries introduced
- [ ] All validation levels 1-4 pass; eval bar met (grounding 100%, recall 100%, judge ≥5/6 per dataset)
- [ ] Numeric-grounding check is a real runtime gate in all three `run_X` functions, not just an eval-time check
- [ ] Logfire trace shows all four new spans (three agents + `peer_discovery_stage`) with the listed attributes
- [ ] No regressions in existing 111 unit tests or Phase 1-3 eval datasets
- [ ] `fetch_all()`'s 6-tuple change updated at its one call site + CLAUDE.md's Commands section
- [ ] CLAUDE.md Current State, `agents.md`, `data-layer.md` updated per the tasks above

## COMPLETION CHECKLIST

- [ ] Tasks executed in order (Phase A validated before starting Phase B — this is the largest
  phase yet; don't discover a data-layer bug after three agents are already built on top of it)
- [ ] Full unit suite + all six eval datasets (3 existing + 3 new) pass
- [ ] Manual trace inspection done against a real ticker
- [ ] Plan file updated with any deviations taken during implementation (this project's standing convention)

## NOTES

- **Peer discovery is single-page (no atom-feed pagination)** — a deliberate MVP simplification.
  SIC=7370 alone returned 40 candidates on `count=40` with a real `rel="next"` link confirming
  more exist. **Correction from live execution**: the original plan conflated "how many raw
  candidates to fetch from the feed" with "how many usable (cik, ticker) pairs to return," passing
  `_MAX_PEER_CANDIDATES_TRIED` (15) as the feed's own `count` param. Live-verified against real
  GOOGL/SIC-7370 data that most raw feed entries in registration order have no active ticker
  (shells/SPACs/delisted filers), so a 15-entry page legitimately returned **zero** usable peers.
  Fixed: `peers_by_sic()` always fetches a full `_SIC_FEED_PAGE_SIZE = 100` page regardless of the
  caller's `limit`, which only caps the *returned* pair count. Re-verified live post-fix: 15 of 100
  candidates now yield 8+ with resolvable shares_outstanding, comfortably clearing
  `_TARGET_PEER_COUNT = 5`. See "Execution Deviations" below for the full live-validation account.
- **Cost/latency**: this phase adds real *EDGAR-call-count* latency (peer discovery: up to 15
  candidates × ~4 sequential-per-candidate lookups, throttled to ~8 req/s, mitigated by
  `asyncio.gather`-ing the candidate batch and by the existing 7-day cache making repeat runs
  against the same ticker nearly free) but **no new $ cost** beyond three more Sonnet-tier calls
  (cheap, same tier as Financial Statements/Filings/Transcript Analysts — expect low cents per
  run, nowhere near the Investigator's $0.36-$1.14/flag). Worth a real latency measurement during
  Level 4 manual validation against the PRD's ~5 minute/run ceiling, since this is the first phase
  where a deterministic stage (not an LLM call) could plausibly be the slowest part of a run.
- **ERP/terminal-growth constants are stated assumptions, not researched-and-cited figures** —
  5.5% and 2.5% respectively, chosen as conventional, defensible round numbers (roughly
  Damodaran-style historical implied-ERP range and long-run nominal-GDP-ish terminal growth) per
  the skill doc's explicit instruction that these be disclosed as assumptions rather than derived
  from a data source (none free exists). If real DCF outputs look systematically off during live
  validation, these are the first two numbers to revisit — not something to tune per-ticker.
  Investment-memo-writing skill note: they still must be displayed as assumptions in memo text.
  Deferred to Phase 6 alongside every other cost/threshold-tuning decision.
- **The numeric-grounding gate's "whole summary lost on one bad number" failure mode** (vs. Phase
  1-3's per-candidate drop) is a real, accepted tradeoff — flagged in Data Contracts above. Watch
  eval `grounding_passed` rates during Level 3; a dataset showing frequent fallback-summary firing
  (rather than a genuinely well-grounded narrative) would be a real signal the prompt needs
  tightening, not that the gate should be loosened.
- **`ValuationAssumptions.risk_free_rate` availability is now a hard dependency for the entire
  Valuation section** — if FRED's `DGS10` series has an outage or the alias is ever renamed, the
  whole `ValuationResult` degrades (see Edge Cases). This is a new single point of failure this
  phase introduces; worth a real look during Phase 6 hardening if it turns out to matter live.
- **Business Overview (memo §3)** is *not* fully solved by Sector Analyst's `SectorAnalystOutput`
  — per the discussion that led to this plan, Sector Analyst's job is peer-*relative* positioning,
  not a general business description. The skill doc's "10-K Item 1 + XBRL segment data" for §3
  still needs the Synthesizer (Phase 5) to read `FilingSections.item_1_business` directly. Not
  this phase's problem to solve, but worth remembering when Phase 5 is planned so §3 doesn't fall
  through a gap between "Filings Analyst didn't cover it" and "Sector Analyst wasn't meant to."

---

## EXECUTION DEVIATIONS (post-implementation)

Phase A-D fully implemented and validated (Levels 1-4; Level 5 N/A, `pipeline.py` doesn't exist
until Phase 5). 157 unit tests passing (up from 111 at the Phase 3 baseline — 46 new), all three
new eval datasets passing cleanly across repeated runs (0 grounding-fallback triggers, 0 LLMJudge
failures, all recall checks pass), live-verified end-to-end against real GOOGL data. Several real
bugs were caught only by live validation, not by unit tests or the eval datasets' first pass — all
fixed, all now regression-tested. Documented here in full per this project's standing convention.

### 1. A real design gap: `TAG_ALIASES` is iterated wholesale — caught before it shipped

Adding `cash_and_equivalents` directly into the shared `TAG_ALIASES` dict (as originally sketched
in the plan's Phase A §1) would have silently added a spurious `CoverageGap` to *every* company's
`FinancialAnalystOutput` forever — `get_financial_statement_bundle()` iterates `TAG_ALIASES`
wholesale to build every `FiscalPeriod`, and `FiscalPeriod` has no `cash_and_equivalents` field.
Caught during implementation, before any test ran. Fixed: a new, separate
`PEER_ONLY_TAG_ALIASES` dict (`data/tag_aliases.py`), resolved via the same `resolve_concept()`
(extended to check both dicts) but never iterated by the FiscalPeriod-building loop.

### 2. Agent output types narrowed after first draft — model-owned metadata that was never trusted

All three agents' first draft used one `output_type` for both the agent's own structured output
*and* the final stage return type (`SectorAnalystOutput` etc., carrying `ticker`+`coverage_gaps`).
Caught while writing the first plumbing test: `run_sector_analyst()` never actually reads
`agent_output.ticker`/`.coverage_gaps` — it always rebuilds those from the real `SectorPeerData`
input, so asking the model to produce them was pure surface area for a value that's discarded
either way. Split into `*AgentOutput` (just `summary: str`, the real `output_type=`) vs. the
stage's own `*Output` type, matching Phases 1-2's "don't ask the model for metadata it shouldn't
own" idiom even though there's no candidate/promotion step here.

### 3. Six real numeric-grounding false-positives, found only by live model output — not by unit
tests or the first eval-dataset pass

`agents/numeric_grounding.py`'s `_NUMBER_RE`/`expand_known_numbers` were written and unit-tested
against hand-picked strings before any real model call. Every one of the following was invisible
to those tests and only surfaced once the three eval datasets ran against a real model — each is
now a permanent regression test in `test_numeric_grounding.py` and/or the relevant agent's test
file:

1. **"10Y"/"2Y" (Treasury-maturity labels glued to a letter)** parsed as the number `10`/`2` —
   this codebase's own FRED series IDs are exactly the vocabulary a macro narrative reaches for.
2. **A subtler recurrence of #1**: a plain greedy `\d+` backtracks to a shorter digit run ("1" out
   of "10") to satisfy the trailing letter-exclusion lookahead once the full run fails it — fixed
   with atomic groups (`(?>...)`), not possessive quantifiers alone (Python's `re` doesn't compose
   `?+` across a `?` group the way `\d++` composes with `\d`).
3. **"10-year" (the model's actual, more idiomatic phrasing over "10Y")** — same category as #1,
   different separator (hyphen instead of none). Caught in `evals.macro_analyst`'s live run.
4. **"$1,981.7" (comma-thousands separators)** split into "1" + "981.7" by a plain `\d+` pattern —
   routine for any real dollar figure in the thousands+. Caught in `evals.valuation_interpreter`.
5. **"2026-08-17" (ISO dates, e.g. `risk_free_rate_as_of` cited verbatim)** split into "2026" (a
   real year, filtered) plus "-08" and "-17" (parsed as -8.0/-17.0, not filterable as years) —
   fixed by stripping ISO dates entirely before number extraction.
6. **"3.99%-4.02%" (a range with a bare ASCII hyphen, no spaces)** had its second endpoint parsed
   as `-4.02` instead of `+4.02` — fixed by only treating a leading hyphen as a minus sign when
   *not* immediately preceded by a digit or `%`.
7. **A percent-difference computed as the wrong sign or wrong reference point**: `combinations()`
   yields each pair in one arbitrary order, and the original code only computed one signed
   direction per pair — "a 47% discount" (positive) could fail to match a same-magnitude negative
   transform. Fixed by adding `abs()` variants of every percent-difference alongside the signed
   ones.
8. **Legitimate citations of the input's own non-numeric-lookalike fields** — a model verbatim-
   citing `SectorPeerData.sic_code` ("SIC 7370 peers") or a number embedded in a `CoverageGap`'s
   own `reason` text (e.g. "found 1, needed >= 2", passed through from upstream) has nothing to
   ground against unless that source text is itself scanned. Fixed by adding `sic_code` directly
   to Sector's known-number set, and by running `extract_numbers()` over every `CoverageGap.reason`
   in both Sector's and Valuation Interpreter's collectors (reusing the same extraction function
   the check itself uses — a citation of real input text is, by construction, always groundable).
9. **`DCFScenario.discount_rate`/`.terminal_growth` per scenario were never collected** — only
   `ValuationAssumptions`' base-case rate was, but the model legitimately narrates the real bull/
   bear rates too (`dcf()`'s ±100bps/±50bps deltas). Fixed by collecting all three scenarios' own
   rates, not just the base case's.

**Takeaway carried into future phases**: a numeric-extraction-and-match grounding mechanism cannot
be fully validated by hand-picked unit-test strings alone — real model prose reliably finds every
formatting convention (ranges, thousands separators, dates, maturity-label shorthand) a synthetic
test author doesn't think to write. The eval datasets' first live run against a real model is what
actually exercised this, consistent with PRD §9's annotation-to-fix flywheel — this is that
flywheel firing during initial implementation rather than after ship, the same pattern noted in
the Phase 1 data-layer bugs (`data-layer.md` bugs #3/#4) and the Phase 3 Investigator's
multi-angle-rule bug.

### 4. `bull_scenario_undefined_present_value`, not `bear_scenario_...` — a plan-authoring error,
caught before any code was written against it

The original plan's case list (Testing Strategy section) named a case
`bear_scenario_undefined_present_value`. Working through the actual math (`dcf()`'s bear leg adds
+100bps to the discount rate and *subtracts* 50bps from terminal growth — both changes that move
`discount_rate - terminal_growth` *further* from the `<=` boundary, making bear structurally the
scenario *least* likely to go undefined) showed this was impossible: bear can never be undefined
while base is valid. The *bull* leg (-100bps discount rate, +50bps terminal growth) is the one
that moves toward the boundary. Corrected in `evals/valuation_interpreter.py`'s case name and
inputs before implementation, not discovered by a failing test — verified independently with a
standalone script before trusting the corrected case, same "verify the formula, don't just trust
the label" discipline as the Phase 0 valuation math itself.

### 5. Peer discovery: feed page size vs. returned-candidate cap conflated — the one bug that
actually broke a live end-to-end run

Described in full in NOTES above. Summary: `discover_sector_peers()` → `peers_by_sic(sic_code,
exclude_cik, limit=_MAX_PEER_CANDIDATES_TRIED)` passed `limit` (15) straight through as the SIC
feed's own `count` param, so only 15 raw candidates were ever fetched before cross-referencing
against `company_tickers.json`. Live-verified against real GOOGL/SIC-7370 data: **zero** of those
15 raw candidates had an active ticker (SIC 7370's registration-ordered entries are dominated by
shells/SPACs/delisted filers in that range), so `discover_sector_peers()` legitimately returned
zero peers and the whole Valuation section degraded to DCF-only — not wrong given the code as
written, but not the intended behavior. Fixed: `_SIC_FEED_PAGE_SIZE = 100` (the confirmed-working
page size from this phase's own live research) is now always used for the feed fetch, decoupled
from `limit`, which only caps the number of *returned* pairs after cross-referencing. Re-verified
live post-fix: 15 of the 100-candidate page have a resolvable price+shares_outstanding, comfortably
clearing `_TARGET_PEER_COUNT = 5`. New regression test:
`test_peers_by_sic_fetches_full_feed_page_regardless_of_small_limit`.

**A second, real (not a bug) finding from the same live run, worth carrying into Phase 5/6
planning**: even with peer discovery working correctly, the *quality* of a SIC-code-based peer set
is genuinely poor for a company like GOOGL. SIC 7370 ("Services-Computer Programming, Data
Processing, Etc.") is broad enough to span micro-cap/shell companies and Alphabet in the same
bucket — the live run's 5 discovered peers (YYAI, APP, BRGX, BLND, BBLR) were a mix of one real
large-cap comparable (APP/AppLovin) and several small/loss-making names, producing a peer-median
P/E of *-0.18* (mechanically correct, not a bug — `peer_multiples()` doesn't and shouldn't filter
negative earnings) that both Sector Analyst and Valuation Interpreter correctly recognized as a
low-quality, low-confidence benchmark rather than presenting it as a real signal. The system
degrades honestly (this is the "good vs. boilerplate" bar working as intended), but the underlying
peer-set *quality* — not just quantity — is a real, permanent limitation of pure SIC-code matching,
not something this phase's fix addresses. Worth a size/liquidity filter (e.g. minimum revenue
threshold before a candidate counts as a peer) as a Phase 6 hardening candidate if peer-comps
quality turns out to matter for real memo output — flagged honestly rather than overstated as
solved.

### Live-verified (GOOGL, 2026-08-19)

End-to-end manual run (Level 4) against real EDGAR/FRED/Tiingo/Anthropic data, post all fixes
above: `fetch_all()` returned the new 6-tuple correctly (SIC 7370, in_scope=True, 61 financial
periods, 13 annual/10-K periods after filtering); peer discovery found 5 peers; Sector Analyst,
Macro Sensitivity Analyst, and Valuation Interpreter all produced grounded, non-fallback narratives
on the first attempt, each correctly citing real numbers (GOOGL's real P/E ~31.9x, real trailing
FCF from $11.3B to $73.3B across 13 filed annual periods, a real 4.71% DGS10-derived risk-free
rate, real per-scenario DCF present values of ~$418B-$634B) and each correctly disclosing
assumptions/gaps in prose exactly as instructed (bull/base/bear discount rates stated as "assuming
...", the missing `latest_total_debt` field described as "None, not zero" rather than omitted or
zeroed). `sector_analyst_stage` span confirmed firing in the Logfire console output.

### 6. `peer_discovery_stage` span was planned but never actually written — caught in a post-report
follow-up check, not the original Level 4 pass

The Phase C spec (and the "Ready for Commit" report) claimed a `peer_discovery_stage` span existed.
It didn't — `data/peer_discovery.py` had no `logfire` import or span at all until a user follow-up
question ("is there anything to check on Logfire?") prompted re-checking the claim against the
actual file. Fixed: added the span (`ticker`, `sic_code`, `candidates_scanned`, `peers_found`).

A second, subtler bug surfaced while verifying the fix: the span was a **silent no-op**
(`LogfireNotConfiguredWarning`, no data recorded) when `discover_sector_peers()` was called without
some *other* module having already imported `agentic_fundamental_analyst.observability` first —
every agent module does this at import time (`from agentic_fundamental_analyst import config,
observability`), but `data/peer_discovery.py` is a plausible standalone entry point with no agent
dependency, and this project has never previously put a span on a purely deterministic module (no
prior phase's deterministic stage — dedup, ratio computation — has a span at all, so this gap was
structurally new to Phase 4, not a regression). Fixed by adding the same `config`/`observability`
import to `data/peer_discovery.py`. Re-verified live: the span now fires whether or not an agent
module was imported first.

**Takeaway**: verify a claimed observability change by checking the actual diff/grep, not by
recalling the plan's intent — a plan spec is not evidence the corresponding line of code exists.
