# PRD: Agentic Fundamental Analyst

## 1. Executive Summary

Given a single US-listed equity ticker, the system produces a grounded investment memo — a full write-up culminating in a Buy/Hold/Sell rating and conviction tier — using only free data sources. Its defining behavior: when an anomaly appears in the fundamentals (e.g. a capex spike), the system doesn't mechanically flag it. It investigates the anomaly using outside context (web search) and reaches an explicit verdict — benign, concerning, or unresolved — with cited evidence. The same anomaly resolves differently depending on context (e.g. AI-buildout capex backed by segment growth vs. the same spike alongside a declining core business), because the investigation is grounded in real evidence, not a static threshold.

**Consumer**: the builder, as a personal research tool, tested continuously against real tickers during development — which is why the entire data layer is built on free APIs with zero marginal cost.

**MVP goal**: given one US-listed, SEC-filing ticker for a standard non-financial operating company, run `run_memo_pipeline(ticker)` and produce one `Memo` — grounded, typed, and traceable end to end — using SEC EDGAR, FRED, and Tiingo/Stooq only. Banks, insurers, and REITs are explicitly excluded from the MVP (see §7) — their financial statement structures don't fit the ratio/valuation framework this system is built around, and applying it to them risks misleading rather than merely incomplete output.

---

## 2. Mission & Core Principles

**Mission**: Build a fundamental-analyst system where agents interpret and deterministic code computes, so every investigation is auditable, every claim is groundable, and the whole system is cheap enough to run constantly during development.

**Core principles**:
1. **Agents interpret; deterministic code fetches and computes.** API calls, filing parsing, ratio math, and valuation math are plain, unit-tested Python — never wrapped in an agent.
2. **Every inter-stage boundary is a typed Pydantic model, never a dict.**
3. **No agent is "done" until it has a labeled eval dataset**, built alongside the feature, not after.
4. **Absence of data is never a bearish signal.** Missing data propagates explicitly as a coverage gap in the memo, never coerced into a negative (or positive) signal.
5. **Deterministic evaluators are preferred over recall checks, which are preferred over LLM judges**, in that order, for every eval written.

---

## 3. Final Artifact Specification

### Memo structure (10 sections, in order)

| # | Section | MVP status |
|---|---|---|
| 1 | Executive Summary & Recommendation | Included |
| 2 | Investment Thesis | Included (reframed — no consensus comparison; thesis pillars compare against reverse-DCF, own historical trend, or macro backdrop) |
| 3 | Business Overview | Included |
| 4 | Financial Analysis | Included |
| 5 | Earnings Quality & Red Flags | Included |
| 6 | Valuation | Partial — trailing DCF & self-built peer comps included; consensus/forward-multiple comparisons deferred |
| 7 | Catalysts | Partial — filing-calendar/disclosed-schedule events included; guidance/estimate-revision-driven catalysts deferred |
| 8 | Risks & Mitigants | Included |
| 9 | Recommendation & Sizing | Partial — rating + qualitative conviction tier included; precise dollar/% position sizing deferred (no portfolio-level state) |
| 10 | Appendix / Sourcing | Included — mandatory, mechanical enforcement of the traceability rule |

Full section-by-section guidance, the earnings-quality checklist, and the good-vs-boilerplate criteria live in the `investment-memo-writing` skill and are the source of truth for prompt construction.

### Top-level output model (sketch)

```python
class Rating(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"

class ConvictionTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class SourcedFigure(BaseModel):
    value: float
    source: str      # e.g. "EDGAR:CIK0000320193:us-gaap:Revenues:CY2024Q4"
    as_of: date

class MemoSection(BaseModel):
    title: str
    content: str
    cited_figures: list[SourcedFigure]

class Memo(BaseModel):
    ticker: str
    rating: Rating
    conviction: ConvictionTier
    generated_at: datetime
    sections: list[MemoSection]
    coverage_gaps: list[str]
    investigations: list[InvestigationVerdict]
```

**What "grounded" means**: every numeric claim appearing in any `MemoSection.content` must resolve to a `SourcedFigure` (or an upstream typed field it derives from). This is checked deterministically by a `GroundingEvaluator` — not by a judge — both in eval runs and, in the MVP, as a hard assertion before a memo is considered complete.

---

## 4. System Architecture

### Pipeline (fixed, agentic islands — no orchestrator agent)

```
[Phase 0: deterministic fetch + cache: EDGAR / FRED / Tiingo+Stooq]
        │
        ▼
┌───────────────────────────────────────────┐
│ parallel: Financial Statements Analyst      │
│           Filings Analyst                   │
│           Transcript Analyst                │
└───────────────────────────────────────────┘
        │  list[Flag] (possibly empty per analyst)
        ▼
   deterministic exact-dedup  →  Flag Consolidator (semantic merge)
        │  list[ConsolidatedFlag]
        ▼
   Investigator × N (parallel, one run per flag)
        │  list[InvestigationVerdict]
        ▼
┌───────────────────────────────────────────┐
│ parallel: Sector Analyst                     │
│           Macro Sensitivity Analyst           │
│           Valuation Interpreter               │
└───────────────────────────────────────────┘
        │
        ▼
   Synthesizer (draft pass) → MemoDraft
        ▼
   Red-Team → RedTeamAttack
        ▼
   Synthesizer (resolve pass) → Memo   ← ships
```

Driven by a single `async def run_memo_pipeline(ticker: str) -> Memo`, using `asyncio.gather` within each parallel block. No dynamic routing, no orchestrator agent — every run executes every stage.

### Agent roster

| Agent | Role | Input type | Output type | Model tier | Capabilities | Agentic loop |
|---|---|---|---|---|---|---|
| Financial Statements Analyst | Interpret computed ratios/trends | `FinancialStatementBundle` | `FinancialAnalystOutput` | Claude Sonnet | none | No |
| Filings Analyst | Interpret filing text (Item 1, 1A, MD&A, 8-K events) | `FilingSections` | `FilingsAnalystOutput` | Claude Sonnet | none | No |
| Transcript Analyst | Interpret opportunistic transcript text (or explicit unavailable) | `TranscriptInput \| None` | `TranscriptAnalystOutput` | Claude Sonnet | none | No |
| Flag Consolidator | Semantic merge of cross-analyst flags (after exact-dedup) | `list[Flag]` | `list[ConsolidatedFlag]` | Claude Haiku | none | No |
| **Investigator** | Hypothesis-driven investigation of one flag | `ConsolidatedFlag` + context | `InvestigationVerdict` | Claude Opus | `WebSearch`, `WebFetch`, `Thinking` | **Yes — the only agentic loop in the system** |
| Sector Analyst | Interpret peer/segment context | `SectorPeerData` | `SectorContext` | Claude Sonnet | none | No |
| Macro Sensitivity Analyst | Interpret macro exposure | `MacroSeriesBundle` + company profile | `MacroContext` | Claude Sonnet | none | No |
| Valuation Interpreter | Narrate deterministic valuation output | `ValuationResult` | `ValuationContext` | Claude Sonnet | none | No |
| Synthesizer — draft pass | Draft the memo from all upstream typed context | all upstream outputs | `MemoDraft` | Claude Opus | none | No |
| Red-Team | Attack the draft as hard as evidence allows | `MemoDraft` + upstream context | `RedTeamAttack` | Claude Opus | none | No |
| Synthesizer — resolve pass | Answer or downgrade every attack | `MemoDraft` + `RedTeamAttack` | `Memo` | Claude Opus | none | No |

Model tiers above are a starting assignment, not fixed — routing changes must be justified by eval results (Section 10).

### Deterministic components (explicitly not agents)

- `run_memo_pipeline()` — the orchestrator itself
- `EdgarClient`, `FredClient`, `PriceClient` — all API fetching
- Local cache layer (disk/SQLite, TTL per source)
- Filing section extraction (HTML/text parsing into `FilingSections`)
- `ratios.py` — all ratio math (DSO, Sloan accruals, cash conversion, capex/D&A, Beneish components)
- `valuation.py` — all DCF and peer-multiple math
- Exact-match flag deduplication (same metric + period across analysts)
- `GroundingEvaluator` — the traceability check itself

These are code, not agents, because their correctness is checkable by unit test — there is no judgment call to make.

---

## 5. Data Layer Specification

| Source | Data obtained | Cost | Auth | Cache policy |
|---|---|---|---|---|
| SEC EDGAR (`data.sec.gov`, `www.sec.gov`, `efts.sec.gov`) | Filings (10-K/10-Q/8-K/DEF 14A), XBRL company facts/concepts, full-text search, Forms 3/4/5 | Free, no key (10 req/s limit; requires descriptive `User-Agent`) | User-Agent header only | 7 days (filed data changes rarely) |
| FRED (`api.stlouisfed.org`) | Macro series: `FEDFUNDS`, `DGS10`, `DGS2`, `T10Y2Y`, `CPIAUCSL`, `GDP`, `UNRATE`, `VIXCLS`, etc. | Free, instant key (120 req/min with key) | API key | 1 day |
| Tiingo | Daily OHLCV, primary price source | Free tier (1,000 req/day, 50/hour) | API key | 1 day |
| Stooq | Bulk historical daily bars, backfill only | Free, no key, undocumented quota | none | on first fetch, then reused |

**Parsing responsibilities**: filing section extraction (Item 1, Item 1A, MD&A, 8-K item bodies) happens entirely in the data layer as deterministic HTML/text parsing. Agents receive already-extracted, already-typed sections — never raw filing HTML.

**Validation at ingest**: FRED's `"."` missing-value sentinel is coerced to `None` in a Pydantic validator; XBRL tag lookups use a fallback alias list per concept (e.g. `Revenues` vs. `RevenueFromContractWithCustomerExcludingAssessedTax`) and record a `CoverageGap` rather than a false zero when no alias resolves; non-calendar fiscal years are normalized using each filer's actual `fy`/`fp`/`start`/`end` fields, never the `frames` endpoint's `CY{year}` label alone; the filer's SIC code (from the EDGAR submissions endpoint) is checked against the excluded-sector list (banks, insurers, REITs — §7) at intake, before any other fetching happens, so an out-of-scope ticker fails fast with a clear reason rather than producing a memo the ratio framework can't support.

---

## 6. Data Contracts

Core shared models (illustrative, not exhaustive):

```python
class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Flag(BaseModel):
    metric: str
    period: str
    severity: Severity
    description: str
    source: SourcedFigure

class ConsolidatedFlag(BaseModel):
    flags: list[Flag]          # one or more merged Flags
    summary: str

class VerdictType(str, Enum):
    BENIGN = "benign"
    CONCERNING = "concerning"
    UNRESOLVED = "unresolved"

class InvestigationVerdict(BaseModel):
    flag: ConsolidatedFlag
    verdict: VerdictType
    hypothesis: str
    evidence: list[str]        # cited URLs/snippets from WebSearch/WebFetch
    confidence: float

class CoverageGap(BaseModel):
    field: str
    reason: str                 # e.g. "no XBRL tag alias resolved", "no 8-K transcript exhibit found"
```

**Optional-field policy**: any field sourced from a category the MVP can't reliably cover (transcripts, consensus estimates) is `Optional` and paired with an explicit `CoverageGap` entry when absent — never silently omitted, never defaulted to a value that could read as a signal.

---

## 7. MVP Scope

**Company Universe**
- ✅ US-listed, SEC-filing, standard non-financial operating companies (manufacturing, tech, retail, industrials, healthcare products, etc.)
- ❌ Banks and other depository institutions — no revenue/COGS/inventory structure, capex/D&A and leverage-based accrual signals are meaningless or actively misleading (leverage is the business model, not a red flag)
- ❌ Insurers — combined ratio, underwriting result, and reserve development are the metrics that matter; none are in the current checklist
- ❌ REITs — GAAP net income is dominated by real-estate depreciation and isn't a meaningful earnings measure; FFO/AFFO and cap-rate/NAV valuation aren't supported by the current data layer or valuation math
- Enforcement: ticker intake validates SIC code (already fetched from EDGAR for peer-comp purposes in the Sector Analyst) against an excluded-sector list and rejects out-of-scope tickers explicitly, rather than silently producing a low-quality memo

**Data Sources**
- ✅ SEC EDGAR, FRED, Tiingo (+ Stooq backfill)
- ❌ Earnings call transcripts as a general capability (only opportunistic 8-K exhibits, ~20-30% coverage, used when found)
- ❌ Consensus analyst estimates / price targets (no free source exists)
- ❌ Real-time/intraday pricing, short interest, institutional ownership/crowding

**Agents**
- ✅ All 9 roles in Section 4
- ❌ Any orchestrator/router agent — the pipeline is fixed

**Evals & Testing**
- ✅ Golden-file unit tests for the data layer; a labeled Pydantic Evals dataset per agent before that agent ships; trajectory evals for the Investigator
- ❌ Continuous/automatic re-training or fine-tuning of any kind

**Observability**
- ✅ Logfire from Phase 1 onward; one trace per memo run; per-stage spans with cost/signal attributes
- ❌ Third-party OTel backends (deferred — the instrumentation is OTel-native so this is a config change, not a redesign, if ever needed)

**Orchestration**
- ✅ Plain async function, fixed sequence, `asyncio.gather` for parallel blocks
- ❌ Dynamic routing, durable execution (Temporal/DBOS), multi-ticker batch/screening

---

## 8. Evaluation & Testing Strategy

Layered, bottom-up:
1. **Golden-file unit tests** — data layer (ratio/valuation math against known-ticker fixtures). No LLM involved.
2. **Per-agent Pydantic Evals datasets** — `Case`s with typed inputs and labeled expected flags/verdicts, gated before each agent ships.
3. **Trajectory evals** — Investigator only, using `HasMatchingSpan` to assert real tool-call behavior (did it search before concluding, how many calls).
4. **End-to-end groundedness and consistency evals** — the deterministic `GroundingEvaluator` run against full memo outputs, plus the two canonical capex-spike golden cases (benign vs. concerning).

**Evaluator preference order** (applied at every layer): deterministic checks → recall checks (`Contains`, `IsInstance`, set comparison) → `LLMJudge`/`GEval`, used only where no deterministic or recall check can substitute (e.g. judging whether a red-team attack is substantive vs. superficial).

**TestModel usage**: all CI plumbing tests (pipeline wiring, output-type validation) run against `TestModel`/`FunctionModel` — zero API spend in CI. `FunctionModel` specifically scripts the Investigator's tool-call sequence for deterministic offline testing of the one agentic loop.

**Tracked but not pass/fail**: directional hit rate of Investigator verdicts against real-world outcomes over time, cost-per-run trend, latency-per-stage trend — these are long-run Logfire dashboard metrics, not CI gates.

---

## 9. Observability Strategy

- `logfire.instrument_pydantic_ai()` enabled globally from Phase 1 onward; every agent constructed with `name=` for identifiable spans.
- **One trace per pipeline run**, with `ticker` attached as a baggage attribute so every span in the trace — LLM and deterministic alike — is filterable by ticker.
- **Per-stage spans** wrap both agent calls and deterministic stages (data fetch, dedup), each carrying custom attributes: flag counts, verdict, tool-call count, cost (`operation.cost` rollup).
- **Dashboards**: cost-per-run, latency-per-stage, and eval-score-over-time (Pydantic Evals reports also emit to Logfire, tagged by phase/dataset version).
- **Annotation → eval flywheel**: any disagreement with a real output gets pulled from its trace (inputs are already typed and captured), hand-corrected, and added as a new `Case` to the relevant dataset — this is how eval coverage grows past what's anticipated up front.

---

## 10. Cost & Model Routing

- Model tier per agent as listed in Section 4's roster; any change to that routing must be justified by a measurable eval-score or cost delta, not intuition.
- **Prompt-caching convention**: stable, long-lived content (filing text, the financial statement bundle) is placed first in the message/context for each agent call, so it can be cached across repeated runs during development.
- **Spend limits on the Investigator** (the one component with open-ended, potentially multi-call cost): deferred as an open decision to Phase 6 — either manual budget enforcement on Logfire's `operation.cost` attribute at the stage boundary, or `pydantic-ai-harness`'s `SpendLimits` capability, decided once its exact API is verified against primary docs.

---

## 11. Success Criteria

**MVP is successful when**: given a real US-listed ticker, `run_memo_pipeline(ticker)` produces a `Memo` that:
- ✅ Passes the deterministic groundedness evaluator at 100% — no numeric claim without a traceable source
- ✅ Correctly resolves both canonical capex-spike cases (AI-buildout-with-growth → benign; same spike with declining core business → concerning)
- ✅ Surfaces every data-source gap (transcript unavailable, no consensus data) as an explicit `coverage_gaps` entry, never as an implied signal
- ✅ Completes within a proposed cost ceiling of ~$2/run and latency ceiling of ~5 minutes (placeholder targets — to be validated and adjusted once Phase 1-5 costs are actually measured)
- ✅ Every agent in the roster has a passing labeled eval dataset checked into the repo

---

## 12. Implementation Phases

| Phase | Goal | Deliverables | Exit validation |
|---|---|---|---|
| 0 | Deterministic data layer | `EdgarClient`, `FredClient`, `PriceClient`, cache layer, `ratios.py`, `valuation.py` | Golden-file unit tests pass for 2-3 known tickers |
| 1 | First analyst, end-to-end | Financial Statements Analyst; Logfire wired in from this run onward | Labeled eval dataset (capex-spike, margin-compression, clean cases) passes |
| 2 | Remaining analysts + consolidation | Filings Analyst, Transcript Analyst, Flag Consolidator | Per-analyst eval datasets (incl. missing-transcript coverage-gap case) + consolidator merge-accuracy cases pass |
| 3 | Investigator | The one agentic-loop agent, with `WebSearch`/`WebFetch`/`Thinking` | Output evals (both canonical capex cases) **and** trajectory evals (`HasMatchingSpan`, tool-call bounds) pass |
| 4 | Relative context | Sector Analyst, Macro Sensitivity Analyst, Valuation Interpreter (parallel) | Grounding + recall eval cases pass per agent |
| 5 | Synthesis, red-team, full wiring | Synthesizer (draft + resolve), Red-Team, `run_memo_pipeline` end-to-end | End-to-end `GroundingEvaluator` at 100%; both canonical golden memos produced correctly |
| 6 | Hardening | Spend-limit decision + implementation, fallback models, cost/latency/eval dashboards | Full regression suite (all prior datasets) passes as a standing gate |

---

## 13. Future Considerations

- Sector-specific ratio and valuation frameworks for banks, insurers, and REITs (net interest margin/efficiency ratio/capital ratios; combined ratio/underwriting result; FFO-AFFO/cap-rate-NAV, respectively) to lift the Company Universe exclusion in §7
- Paid transcript and consensus-estimate sources, once product scope justifies the marginal cost
- Multi-ticker screening / batch runs
- Portfolio-level state enabling real position sizing
- Dynamic routing or a true orchestrator agent, if a fixed pipeline stops fitting the product
- Durable execution (Temporal/DBOS) if runs need to survive process restarts
- Scheduled/recurring memo refreshes per ticker

---

## 14. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Hallucinated figures in agent output | Deterministic `GroundingEvaluator` blocks any numeric claim that doesn't trace to a typed source field |
| Over-flagging (noise burns Investigator budget on trivial anomalies) | Flag thresholds tuned against labeled eval datasets; exact-dedup + semantic consolidation before any flag reaches the Investigator |
| Sycophantic resolve-pass (caves to red-team without real re-grounding) | Resolve pass must state, per attack, which of the three resolution paths was used (re-ground / downgrade / cut) — checked structurally, not just accepted |
| Cost blowouts from the Investigator's open-ended loop | Phase 6 spend limits; trajectory evals bound expected tool-call count per flag |
| Data-provider drift (SEC/FRED/Tiingo schema or rate-limit changes) | Golden-file tests catch data-layer breakage immediately; cache layer insulates against transient outages |

---

## 15. Appendix

**Repository structure** (current):
- `.agents/references/pydantic-ai-v2.md` — Pydantic AI v2 capability research (agents, capabilities, evals, TestModel, Logfire), versioned as of `pydantic-ai` 2.31.1
- `.agents/references/free-data-sources.md` — free data source research and recommendations
- `.claude/skills/investment-memo-writing/SKILL.md` — memo structure, earnings-quality checklist, section-by-section MVP mapping

**Key external docs**: `pydantic.dev/docs/ai/` (Pydantic AI), `pydantic.dev/docs/logfire/` (Logfire), `data.sec.gov` (EDGAR), `fred.stlouisfed.org/docs/api/fred/` (FRED), `tiingo.com` (prices).
