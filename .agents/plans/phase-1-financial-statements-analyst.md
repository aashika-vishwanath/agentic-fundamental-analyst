# Feature: Phase 1 — Financial Statements Analyst

Validate documentation, existing contracts, and codebase patterns before implementing.
Pay special attention to existing model/enum names — import, don't redefine.

## Feature Description

The first LLM agent in the pipeline: it interprets deterministically-computed earnings-quality
ratios/trends (checklist items #1–#7 in the investment-memo-writing skill) and raises `Flag`s
where warranted, plus a short narrative summary for the memo's Financial Analysis section. This
phase also wires up Logfire globally — every later agent inherits that instrumentation rather
than re-deriving it.

Scope is annual (10-K) periods only. Quarterly trend analysis, and checklist items #8–17 (which
need filing text, 8-K items, proxy statements, or Forms 3/4/5 — none of which this agent
receives), are out of scope here; they land with the Filings Analyst / Transcript Analyst /
Flag Consolidator in Phase 2.

## User Story

As the pipeline (on behalf of the eventual memo reader), I want the raw XBRL financial history
turned into computed ratio trends and then interpreted for red flags, so that later stages
(Investigator, Synthesizer) have a typed, grounded starting point for the Earnings Quality
section instead of raw numbers no one has looked at.

## Problem / Solution Statement

**Problem**: `FinancialStatementBundle` (Phase 0) is raw per-period XBRL data. Nothing yet turns
it into the ratios the earnings-quality checklist actually references, and nothing decides
whether a given ratio value is flag-worthy. That decision requires judgment (is a 2.3x capex/D&A
ratio concerning given the trend, or unremarkable?) — which is exactly what an agent is for. But
the *arithmetic* is not judgment, and CLAUDE.md hard-constrains "never wrap ... a ratio
calculation ... in an agent."

**Approach chosen**: Split this into two closed pieces instead of one.
1. **Deterministic**: `ratios.compute_trend_bundle()` turns `FinancialStatementBundle` →
   `RatioTrendBundle`, a wire-typed model where every ratio is either a real value or an
   explicit `RatioResult(value=None, reason=...)`. This is pure arithmetic reuse of Phase 0's
   `ratios.py` functions — no new math, only pairing/sequencing logic.
2. **Agent**: `financial_statements_analyst` receives *only* `RatioTrendBundle` (never raw
   `FiscalPeriod`s) and outputs `FinancialAnalystAgentOutput` — a summary plus `FlagCandidate`s
   that name a `(metric, fiscal_year, fiscal_period)` triple and a severity/description. **The
   agent's output type has no numeric `value` field at all.** A deterministic grounding pass
   (`run_financial_statements_analyst`, in the same module) then looks up the real
   `RatioResult.value` for every candidate, builds the final `Flag` with a code-constructed
   `SourcedFigure`, and silently drops (logging to `dropped_candidates`) any candidate that
   references a metric/period the input doesn't actually contain a value for.

   This makes structural grounding true **by construction**, not just checked after the fact —
   the LLM cannot cause a wrong number to reach `Flag.source.value`, because it never supplies
   one. A second, looser deterministic check (regex-based numeric extraction from the free-text
   `summary`/`description` fields, described under Testing Strategy) catches the remaining case:
   prose that states a number not defensible from the input, even if the structural `Flag` behind
   it is fine.

**Alternative rejected**: Have the agent restate the ratio's value directly in its output (closer
to the PRD §3 `SourcedFigure` sketch, which the model presumably fills in). Rejected because it
reintroduces exactly the hallucination risk the grounding check exists to catch — an LLM-supplied
`value` would need to be checked against the input anyway, so it's strictly better to never trust
it in the first place and have deterministic code do the lookup.

**Deviation from the PRD's illustrative `SourcedFigure.source` sketch**: PRD §3 shows
`source: "EDGAR:CIK0000320193:us-gaap:Revenues:CY2024Q4"` — an XBRL-tag-level citation. Phase 0's
`FiscalPeriod` does not retain which XBRL tag/accession resolved each field (that provenance is
discarded after `EdgarClient` merges tag aliases — a Phase 0 design already shipped, not something
this phase revisits). So `source` here is a coarser but still fully deterministic, code-built
string: `"ratios.{metric}:{ticker}:{fiscal_year}{fiscal_period}"`. Flagged here rather than
silently diverging; revisit if a later phase threads tag provenance through `ratios.py`.

## Feature Metadata

**Type**: New Capability
**Complexity**: High (first agent + first eval dataset + Logfire bring-up + new contracts + new
deterministic trend layer, all at once)
**Pipeline stage(s)**: Stage 2 (parallel analysts) — this is 1 of the 3 analysts, but the only one
built this phase
**Dependencies**: Phase 0 (`FinancialStatementBundle`, `ratios.py`, `contracts/financials.py`) —
complete. New external deps: `pydantic-ai`, `logfire` (runtime); `pydantic-evals` (dev). New env
vars: `ANTHROPIC_API_KEY`, `LOGFIRE_TOKEN` (both needed only for live/eval runs, never for
`tests/unit`).

## Agent-or-Code Decisions

| Component | Agent or Code | Why |
|---|---|---|
| `compute_period_ratios` / `compute_trend_bundle` (ratio math + period pairing) | Code | Pure arithmetic + sequencing, unit-testable, zero judgment |
| Deciding whether a computed ratio is flag-worthy given the trend | Agent | Requires judgment against a threshold *in context* (e.g. is this capex spike part of a multi-year pattern or a one-off) — the PRD's own checklist frames these as heuristics, not hard cutoffs |
| Narrative summary of the financial trend | Agent | Interpretation/prose synthesis — not derivable mechanically |
| Resolving a `FlagCandidate` into a grounded `Flag` (numeric lookup + `SourcedFigure` construction) | Code | The whole point is that this must not be trusted to the model — see Problem/Solution |
| Deriving `coverage_gaps` (data-layer gaps + ratio-unavailable gaps) | Code | Hard constraint: coverage gaps must propagate explicitly, never via LLM discretion |
| Logfire configuration/instrumentation | Code | Infrastructure, not interpretation |

## Data Contracts

### New: `contracts/sourcing.py`
```python
from datetime import date
from pydantic import BaseModel

class SourcedFigure(BaseModel):
    value: float
    source: str      # deterministically built, e.g. "ratios.days_sales_outstanding:GOOGL:2024FY"
    as_of: date       # the period_end this figure belongs to
```

### New: `contracts/flags.py` (generic — reused by every future flag-raising analyst)
```python
from enum import Enum
from pydantic import BaseModel
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class Flag(BaseModel):
    metric: str
    fiscal_year: int
    fiscal_period: str
    severity: Severity
    description: str
    source: SourcedFigure
```
`metric` is a plain `str` here (not this agent's closed `Literal`) because `Flag` must also serve
the Filings Analyst / Transcript Analyst in Phase 2, whose metric vocabularies differ (checklist
items #8–17: auditor changes, going-concern language, etc.) — narrowing belongs on each agent's
own candidate type, not on the shared contract.

### Extend: `contracts/ratios.py` (currently only `RatioResult` — add below it)
```python
from datetime import date
from agentic_fundamental_analyst.contracts.financials import CoverageGap

class PeriodRatios(BaseModel):
    fiscal_year: int
    fiscal_period: str
    period_end: date
    days_sales_outstanding: RatioResult
    receivables_growth_vs_revenue_growth: RatioResult
    inventory_growth_vs_cogs_growth: RatioResult
    sloan_accruals: RatioResult
    cash_conversion_ratio: RatioResult
    capex_to_depreciation_ratio: RatioResult
    days_inventory_outstanding: RatioResult   # intermediate; not independently flaggable
    cash_conversion_cycle: RatioResult        # always None (permanent Phase 0 gap — see CLAUDE.md)
    beneish_m_score: RatioResult
    # raw values carried through so the agent's narrative can cite real magnitudes
    revenue: float | None
    net_income: float | None
    capex: float | None
    depreciation_amortization: float | None

class RatioTrendBundle(BaseModel):
    ticker: str
    cik: str
    periods: list[PeriodRatios]   # chronological, oldest first, 10-K/annual only
    coverage_gaps: list[CoverageGap]   # passed through unchanged from FinancialStatementBundle
```

### New: `contracts/financial_analyst.py`
```python
from typing import Literal
from pydantic import BaseModel
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Flag, Severity

FinancialFlagMetric = Literal[
    "days_sales_outstanding",
    "receivables_growth_vs_revenue_growth",
    "inventory_growth_vs_cogs_growth",
    "sloan_accruals",
    "cash_conversion_ratio",
    "capex_to_depreciation_ratio",
    "beneish_m_score",
]
# Deliberately excludes days_inventory_outstanding (intermediate only) and
# cash_conversion_cycle (permanently unavailable — Phase 0 gap).

class FlagCandidate(BaseModel):
    metric: FinancialFlagMetric
    fiscal_year: int
    fiscal_period: str
    severity: Severity
    description: str
    # NOTE: no `value` field — see Problem/Solution. The agent names *what* it
    # thinks is flag-worthy; deterministic code supplies the real number.

class FinancialAnalystAgentOutput(BaseModel):
    """The agent's own output_type — narrower than the final stage output."""
    summary: str
    flag_candidates: list[FlagCandidate]

class FinancialAnalystOutput(BaseModel):
    """What the pipeline stage actually returns, after grounding."""
    ticker: str
    summary: str
    flags: list[Flag]
    coverage_gaps: list[CoverageGap]
    dropped_candidates: list[str] = []   # human-readable, e.g. "beneish_m_score 2021FY: no matching period"
```

**Optional-field policy**: no new `Optional` fields beyond what Phase 0 already established;
`RatioResult.value` is already the vehicle for "this couldn't be computed" and this phase adds
nothing that silently defaults instead of stating a reason.

---

## CONTEXT REFERENCES

### Codebase files to READ before implementing
- `src/agentic_fundamental_analyst/ratios.py` (all) — Why: every function this phase calls
  already exists; `compute_period_ratios` is purely a composition of these, same
  `RatioResult(value=None, reason=...)` idiom must be followed exactly.
- `src/agentic_fundamental_analyst/contracts/financials.py:25-52` — `FiscalPeriod` /
  `FinancialStatementBundle` field names, and the existing `CoverageGap` model to reuse (do not
  redefine).
- `src/agentic_fundamental_analyst/contracts/ratios.py` — the `RatioResult` model this phase's
  new contracts sit alongside.
- `src/agentic_fundamental_analyst/config.py` — the "load once at import time regardless of
  import order" convention; `observability.py` (new) follows the identical shape.
- `src/agentic_fundamental_analyst/data/fetch.py:29-56` — the closest existing analog for a typed
  entry-point function (`fetch_all`) — same style (module docstring stating purpose + gating,
  typed signature, no dict boundaries) should carry over to
  `run_financial_statements_analyst`.
- `tests/unit/test_ratios.py:1-77` — fixture-construction pattern (hand-built `FiscalPeriod`s
  named `PRIOR`/`CURRENT`/`EMPTY`) to mirror for both the new ratio-trend unit tests and the eval
  dataset's `FinancialStatementBundle` fixtures.
- `pyproject.toml` — exact current dependency/test config to extend, not replace.

### New files to create
- `src/agentic_fundamental_analyst/contracts/sourcing.py` — `SourcedFigure`
- `src/agentic_fundamental_analyst/contracts/flags.py` — `Severity`, `Flag`
- `src/agentic_fundamental_analyst/contracts/financial_analyst.py` — this agent's I/O types
- `src/agentic_fundamental_analyst/observability.py` — Logfire bring-up
- `src/agentic_fundamental_analyst/agents/__init__.py` — package marker
- `src/agentic_fundamental_analyst/agents/models.py` — model-tier constants
- `src/agentic_fundamental_analyst/agents/financial_statements.py` — the `Agent` instance,
  instructions, and `run_financial_statements_analyst()`
- `evals/__init__.py`
- `evals/financial_statements.py` — `Dataset`, `Case`s, evaluators
- `tests/unit/test_ratios_trend.py` — unit tests for `compute_trend_bundle`
- `tests/unit/test_financial_statements_agent.py` — `TestModel` plumbing tests

### Documentation to READ before implementing
- `.agents/references/pydantic-ai-v2.md` §1 (Agent construction, output types), §3 (Evals), §4
  (`TestModel`/`FunctionModel`), §5 (Logfire) — the primary source for every pydantic-ai call in
  this phase. Note its own caveat: pydantic-ai ships near-daily releases; **re-verify the exact
  Anthropic model string and `logfire.configure()` signature against live docs before writing
  code that depends on them** — this doc is a snapshot from 2026-08-17.
- `.claude/skills/investment-memo-writing/SKILL.md` §2 (checklist items #1–#7 — the exact
  detection heuristics to translate into agent instructions) and §1 §4 ("Financial Analysis"
  good-vs-boilerplate criteria — informs the `summary` field's bar).
- [pydantic-ai Agent docs](https://pydantic.dev/docs/ai/core-concepts/agent/) — confirm current
  Anthropic model-string format (e.g. whether a dated suffix is required) before hardcoding
  `agents/models.py`.
- [Logfire configure reference](https://pydantic.dev/docs/logfire/) — confirm `send_to_logfire`
  literal values (this plan assumes `"if-token-present"` exists; verify before using it).

### Patterns to follow

**Deterministic trend computation** (`ratios.py` additions — mirrors existing function style):
```python
def compute_period_ratios(current: FiscalPeriod, prior: FiscalPeriod | None) -> PeriodRatios:
    no_prior = RatioResult(value=None, reason="no_prior_period_available")
    return PeriodRatios(
        fiscal_year=current.fiscal_year,
        fiscal_period=current.fiscal_period,
        period_end=current.period_end,
        days_sales_outstanding=days_sales_outstanding(current),
        receivables_growth_vs_revenue_growth=(
            receivables_growth_vs_revenue_growth(current, prior) if prior else no_prior
        ),
        inventory_growth_vs_cogs_growth=(
            inventory_growth_vs_cogs_growth(current, prior) if prior else no_prior
        ),
        sloan_accruals=sloan_accruals(current),
        cash_conversion_ratio=cash_conversion_ratio(current),
        capex_to_depreciation_ratio=capex_to_depreciation_ratio(current),
        days_inventory_outstanding=days_inventory_outstanding(current),
        cash_conversion_cycle=cash_conversion_cycle(current),
        beneish_m_score=beneish_m_score(current, prior) if prior else no_prior,
        revenue=current.revenue,
        net_income=current.net_income,
        capex=current.capex,
        depreciation_amortization=current.depreciation_amortization,
    )


def compute_trend_bundle(bundle: FinancialStatementBundle) -> RatioTrendBundle:
    annual_periods = sorted(
        (p for p in bundle.periods if p.form == "10-K"),
        key=lambda p: p.period_end,
    )
    periods = [
        compute_period_ratios(period, annual_periods[i - 1] if i > 0 else None)
        for i, period in enumerate(annual_periods)
    ]
    return RatioTrendBundle(
        ticker=bundle.ticker, cik=bundle.cik, periods=periods, coverage_gaps=bundle.coverage_gaps
    )
```

**Agent + deterministic grounding wrapper** (`agents/financial_statements.py`):
```python
from agentic_fundamental_analyst import config, observability  # noqa: F401 — import order matters
import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst.agents.models import FINANCIAL_STATEMENTS_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.financial_analyst import (
    FinancialAnalystAgentOutput,
    FinancialAnalystOutput,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap, FinancialStatementBundle
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.ratios import RatioTrendBundle
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.ratios import compute_trend_bundle

_INSTRUCTIONS = """..."""  # see Phase B task for full text

financial_statements_analyst = Agent(
    FINANCIAL_STATEMENTS_ANALYST_MODEL,
    name="financial_statements_analyst",
    output_type=FinancialAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _ground_candidates(
    trend: RatioTrendBundle, agent_output: FinancialAnalystAgentOutput
) -> tuple[list[Flag], list[str]]:
    by_period = {(p.fiscal_year, p.fiscal_period): p for p in trend.periods}
    flags: list[Flag] = []
    dropped: list[str] = []
    for c in agent_output.flag_candidates:
        period = by_period.get((c.fiscal_year, c.fiscal_period))
        result = getattr(period, c.metric, None) if period else None
        if period is None or result is None or result.value is None:
            dropped.append(f"{c.metric} {c.fiscal_year}{c.fiscal_period}: no matching value")
            continue
        flags.append(
            Flag(
                metric=c.metric,
                fiscal_year=c.fiscal_year,
                fiscal_period=c.fiscal_period,
                severity=c.severity,
                description=c.description,
                source=SourcedFigure(
                    value=result.value,
                    source=f"ratios.{c.metric}:{trend.ticker}:{c.fiscal_year}{c.fiscal_period}",
                    as_of=period.period_end,
                ),
            )
        )
    return flags, dropped


def _ratio_unavailable_gaps(trend: RatioTrendBundle) -> list[CoverageGap]:
    gaps = []
    for period in trend.periods:
        for metric in (
            "days_sales_outstanding", "receivables_growth_vs_revenue_growth",
            "inventory_growth_vs_cogs_growth", "sloan_accruals", "cash_conversion_ratio",
            "capex_to_depreciation_ratio", "beneish_m_score",
        ):
            result = getattr(period, metric)
            if result.value is None:
                gaps.append(CoverageGap(
                    field=f"{metric}:{period.fiscal_year}{period.fiscal_period}",
                    reason=result.reason or "unavailable",
                ))
    return gaps


async def run_financial_statements_analyst(bundle: FinancialStatementBundle) -> FinancialAnalystOutput:
    trend = compute_trend_bundle(bundle)
    with logfire.span("financial_statements_analyst_stage", ticker=bundle.ticker) as span:
        result = await financial_statements_analyst.run(trend.model_dump_json(indent=2))
        flags, dropped = _ground_candidates(trend, result.output)
        span.set_attribute("flag_count", len(flags))
        span.set_attribute("dropped_candidate_count", len(dropped))
    return FinancialAnalystOutput(
        ticker=bundle.ticker,
        summary=result.output.summary,
        flags=flags,
        coverage_gaps=[*bundle.coverage_gaps, *_ratio_unavailable_gaps(trend)],
        dropped_candidates=dropped,
    )
```

**Logfire bring-up** (`observability.py` — mirrors `config.py`'s "load once at import" shape, but
must stay silent/offline in CI where no token exists):
```python
"""Configures Logfire once at import time. Must never require network access or a token to
import cleanly — tests/unit imports agent modules (for TestModel plumbing tests) with no
LOGFIRE_TOKEN set, and CI must stay zero-API-spend / key-free (CLAUDE.md Testing Strategy)."""

import os
import logfire

logfire.configure(send_to_logfire="if-token-present" if os.environ.get("LOGFIRE_TOKEN") else False)
logfire.instrument_pydantic_ai()
```
**GOTCHA**: verify `send_to_logfire="if-token-present"` is a real accepted literal in the
installed `logfire` version before relying on it — fall back to the explicit boolean form
(`bool(os.environ.get("LOGFIRE_TOKEN"))`) if not.

---

## IMPLEMENTATION PLAN

### Phase A: Contracts & Data
- `contracts/sourcing.py`, `contracts/flags.py`, `contracts/financial_analyst.py` (new)
- `contracts/ratios.py` extended with `PeriodRatios`, `RatioTrendBundle`
- `ratios.py` extended with `compute_period_ratios`, `compute_trend_bundle`
- Unit tests for the new ratio-trend functions (period pairing, single-period coverage-gap case,
  10-K filtering)

### Phase B: Core Implementation
- `pyproject.toml`: add `pydantic-ai`, `logfire` to `dependencies`; `pydantic-evals` to the `dev`
  dependency group
- `.env.example`: add `ANTHROPIC_API_KEY=`, `LOGFIRE_TOKEN=`
- `observability.py` (new)
- `agents/models.py`, `agents/financial_statements.py` (new) — the agent, its instructions, and
  `run_financial_statements_analyst`

### Phase C: Integration
- No `pipeline.py` yet (Phase 5) — "integration" this phase means: the module is importable and
  runnable standalone (documented as a new Commands-section entry, mirroring the existing
  "Fetch one ticker live" example), and its Logfire span/attributes are verified against a real
  trace.
- Update `CLAUDE.md` Current State section (mandatory, every phase) and Commands section.
- Fill in `.agents/references/agents.md` and `.agents/references/observability.md` (currently
  stubs) with what was actually built — per their own stated status line and the repo convention.

### Phase D: Evals & Validation
- `evals/financial_statements.py`: `Dataset` with 6 cases (see Testing Strategy)
- `tests/unit/test_financial_statements_agent.py`: `TestModel`-based plumbing tests, zero network

---

## STEP-BY-STEP TASKS

### CREATE `src/agentic_fundamental_analyst/contracts/sourcing.py`
- **IMPLEMENT**: `SourcedFigure` exactly as specified in Data Contracts.
- **PATTERN**: `contracts/ratios.py` (minimal, single-purpose module)
- **VALIDATE**: `uv run python -c "from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure"`

### CREATE `src/agentic_fundamental_analyst/contracts/flags.py`
- **IMPLEMENT**: `Severity(str, Enum)`, `Flag` as specified.
- **PATTERN**: `contracts/intake.py:6-9` (`ExcludedSector(str, Enum)`) for the enum style; note
  `pyproject.toml`'s `ruff.lint.ignore = ["UP042"]` exists specifically to permit `(str, Enum)`.
- **IMPORTS**: `from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure`
- **VALIDATE**: `uv run ruff check src/agentic_fundamental_analyst/contracts/flags.py`

### CREATE `src/agentic_fundamental_analyst/contracts/financial_analyst.py`
- **IMPLEMENT**: `FinancialFlagMetric`, `FlagCandidate`, `FinancialAnalystAgentOutput`,
  `FinancialAnalystOutput` as specified.
- **IMPORTS**: `CoverageGap` from `contracts.financials` (do not redefine); `Flag`, `Severity`
  from `contracts.flags`.
- **GOTCHA**: `FlagCandidate` has no `value` field — do not add one back in; that's the whole
  point of the grounding design.
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/contracts`

### UPDATE `src/agentic_fundamental_analyst/contracts/ratios.py`
- **IMPLEMENT**: append `PeriodRatios`, `RatioTrendBundle` below the existing `RatioResult`.
- **IMPORTS**: `date` from `datetime`; `CoverageGap` from `contracts.financials`.
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/contracts/ratios.py`

### UPDATE `src/agentic_fundamental_analyst/ratios.py`
- **IMPLEMENT**: `compute_period_ratios`, `compute_trend_bundle` per the Patterns section above.
- **PATTERN**: existing functions in this same file — same docstring density, same
  `RatioResult(value=None, reason=...)` idiom.
- **IMPORTS**: `FinancialStatementBundle` from `contracts.financials`; `PeriodRatios`,
  `RatioTrendBundle` from `contracts.ratios`.
- **GOTCHA**: filter to `form == "10-K"` before sorting/pairing — a bundle mixing 10-K and 10-Q
  periods must not pair a 10-K with a 10-Q as "prior."
- **VALIDATE**: `uv run pytest tests/unit/test_ratios_trend.py -q` (write this test file next)

### CREATE `tests/unit/test_ratios_trend.py`
- **IMPLEMENT**: extend the `PRIOR`/`CURRENT` fixtures from `test_ratios.py` into a 3-period
  `FinancialStatementBundle` (add one more year); assert `compute_trend_bundle` output has the
  right period count, right ordering, and that each `PeriodRatios[i]` ratio values match calling
  the underlying `ratios.py` function directly on the same pair. Add a case with a single 10-K
  period only — assert every growth/Beneish `RatioResult` has `reason == "no_prior_period_available"`
  and single-period ratios (DSO, cash_conversion_ratio, capex/D&A) still compute. Add a case
  mixing one 10-K and one 10-Q period — assert the 10-Q is excluded entirely.
- **PATTERN**: `tests/unit/test_ratios.py:1-77`
- **VALIDATE**: `uv run pytest tests/unit/test_ratios_trend.py -q`

### UPDATE `pyproject.toml`
- **IMPLEMENT**: add to `[project] dependencies`: `"pydantic-ai>=2.31.1"`, `"logfire>=4.40.0"`.
  Add to `[dependency-groups] dev`: `"pydantic-evals>=2.31.1"`.
- **GOTCHA**: re-check these version floors against PyPI at implementation time — the reference
  doc itself notes near-daily pydantic-ai releases as of its research date.
- **VALIDATE**: `uv sync` (must resolve cleanly)

### UPDATE `.env.example`
- **IMPLEMENT**: add `ANTHROPIC_API_KEY=` and `LOGFIRE_TOKEN=` lines.
- **VALIDATE**: manual review — no secrets committed, just empty keys (matches existing file's style)

### CREATE `src/agentic_fundamental_analyst/observability.py`
- **IMPLEMENT**: per the Patterns section above.
- **GOTCHA**: must be safely importable with zero env vars set (CI/tests/unit has neither
  `LOGFIRE_TOKEN` nor network) — verify this explicitly, it's the one part of this phase most
  likely to silently break the "network-free unit tests" invariant.
- **VALIDATE**: `LOGFIRE_TOKEN= uv run python -c "from agentic_fundamental_analyst import observability"` (unset/empty token, must not hang, prompt, or raise)

### CREATE `src/agentic_fundamental_analyst/agents/__init__.py`
- **IMPLEMENT**: empty file (package marker), matches `contracts/__init__.py` / `data/__init__.py`.
- **VALIDATE**: `uv run python -c "import agentic_fundamental_analyst.agents"`

### CREATE `src/agentic_fundamental_analyst/agents/models.py`
- **IMPLEMENT**: `FINANCIAL_STATEMENTS_ANALYST_MODEL = "anthropic:claude-sonnet-5"` (or whatever
  the verified current pydantic-ai Anthropic model string is — see GOTCHA).
- **GOTCHA**: verify this exact string against live pydantic-ai docs / a real `agent.run_sync`
  smoke call before trusting it in the eval dataset or manual validation step. This constant will
  grow into a small mapping as Phase 2+ agents are added — do not build that structure now, one
  constant is correct for one agent.
- **VALIDATE**: covered by the manual Level 4 smoke test below (a bad model string fails loudly there)

### CREATE `src/agentic_fundamental_analyst/agents/financial_statements.py`
- **IMPLEMENT**: `_INSTRUCTIONS` (full text — see below), `financial_statements_analyst` Agent
  instance, `_ground_candidates`, `_ratio_unavailable_gaps`, `run_financial_statements_analyst`
  per the Patterns section above.
- **Full instructions text**:
  ```
  You are the Financial Statements Analyst for a fundamental-equity research system.
  You receive a RatioTrendBundle: a company's earnings-quality ratios computed
  deterministically, one entry per annual (10-K) fiscal period, oldest first. Every
  number in it is already correct — never restate a ratio's value from memory, and
  never invent a fiscal year, fiscal period, or ratio name that is not present in
  the bundle.

  Task:
  1. Write a 2-4 sentence `summary` of the company's financial trend across the
     supplied periods -- margins, cash conversion, leverage direction -- specific
     to this company's actual numbers, not generic commentary that could describe
     any company in its sector.
  2. For each period, decide whether any of these seven checklist ratios warrants a
     red flag. These thresholds are a starting point for judgment, not a mechanical
     trigger -- always read a number in the context of the trend across periods:
     - days_sales_outstanding: multi-period uptrend
     - receivables_growth_vs_revenue_growth: gap > ~10 percentage points, persistent
     - inventory_growth_vs_cogs_growth: gap > ~10 percentage points, persistent
     - sloan_accruals: large and rising positive value
     - cash_conversion_ratio: persistently below ~0.8, or trending down
     - capex_to_depreciation_ratio: consistently > ~2x. You have no filing text in
       this input, so you cannot tell whether a spike is disclosed growth capex --
       treat any sustained spike as a candidate flag; a later stage investigates it
       with outside context.
     - beneish_m_score: above the conventional -1.78 threshold
     A period where a ratio's value is null and it carries a reason is a coverage
     gap, not a flag and not evidence of anything -- never treat a missing ratio as
     either bullish or bearish.
  3. Only raise a flag for a (metric, fiscal_year, fiscal_period) combination that
     appears in the bundle with a non-null value for that metric. Do not raise a
     flag for a number you cannot see.
  4. Raising zero flags is a valid, expected outcome for a clean set of financials --
     do not manufacture a flag to seem thorough.
  ```
- **IMPORTS**: see Patterns section.
- **GOTCHA**: `logfire.span(...)` must wrap the `.run()` call, not just the grounding step, so the
  span duration reflects the actual model latency (this is what Level 4 manual validation checks).
- **VALIDATE**: `uv run pyright src/agentic_fundamental_analyst/agents/financial_statements.py`

### CREATE `tests/unit/test_financial_statements_agent.py`
- **IMPLEMENT**: three tests, all offline via `TestModel` + `ALLOW_MODEL_REQUESTS = False`:
  1. Agent runs with default `TestModel()`, output validates as `FinancialAnalystAgentOutput`
     (schema-level plumbing check only).
  2. `TestModel(custom_output_args={...})` scripted with one `FlagCandidate` matching a real
     `(metric, fiscal_year, fiscal_period)` in a hand-built `RatioTrendBundle`/`FinancialStatementBundle`
     fixture, and one referencing a fiscal_year not present in the bundle. Run
     `run_financial_statements_analyst` end-to-end with the agent overridden; assert the first
     becomes a real `Flag` with `source.value` equal to the true ratio value, and the second lands
     in `dropped_candidates`, not `flags`.
  3. A `RatioTrendBundle` where every ratio is `None`-with-reason (single-period case) — assert
     `_ratio_unavailable_gaps` produces one `CoverageGap` per unavailable metric/period.
- **PATTERN**: `.agents/references/pydantic-ai-v2.md` §4 (`agent.override(model=TestModel())`,
  `ALLOW_MODEL_REQUESTS = False` safety net)
- **VALIDATE**: `uv run pytest tests/unit/test_financial_statements_agent.py -q` (must pass with
  no `ANTHROPIC_API_KEY`/`LOGFIRE_TOKEN` set in the environment)

### CREATE `evals/__init__.py` and `evals/financial_statements.py`
- **IMPLEMENT**: see Testing Strategy for full case list. `Dataset(name="financial_statements", cases=[...])`
  with the task function `run_financial_statements_analyst`. Custom
  `FinancialStatementsGroundingEvaluator(Evaluator[FinancialStatementBundle, FinancialAnalystOutput])`:
  for each `flag` in output, recompute `ratios.compute_trend_bundle(ctx.inputs)` and assert
  `flag.source.value` matches the recomputed ratio's value at that period (this doubles as a
  regression check that the deterministic grounding logic itself is correct, not just that the
  agent behaved). Plus a looser numeric-extraction check over `summary` text (regex `-?\d+\.?\d*`,
  tolerant match against any value/derived-percent found in the trend bundle, generous tolerance
  — documented as best-effort in Testing Strategy, not a hard gate).
- **PATTERN**: `.agents/references/pydantic-ai-v2.md` §3 (`Case`, `Dataset`, custom `Evaluator` subclass)
- **VALIDATE**: `ANTHROPIC_API_KEY=<real key> uv run python -m evals.financial_statements` (see
  Level 3 below for the passing bar)

---

## TESTING STRATEGY

### Unit tests (deterministic, CI-safe)
- `tests/unit/test_ratios_trend.py` — `compute_period_ratios`/`compute_trend_bundle` pairing,
  10-K filtering, single-period coverage-gap case.
- `tests/unit/test_financial_statements_agent.py` — `TestModel` plumbing, grounding-drop logic,
  coverage-gap derivation. Zero API spend, zero network (enforced by `ALLOW_MODEL_REQUESTS = False`).

### Eval dataset (Pydantic Evals) — `evals/financial_statements.py`
Cases (each a hand-built `FinancialStatementBundle`, 1-3 years of 10-K `FiscalPeriod`s, mirroring
`test_ratios.py`'s fixture style):
- `clean_financials_no_flags` — steady, healthy ratios across 3 years. **Expected**: `flags == []`.
  This is the over-flagging guard the plan-feature template calls out explicitly.
- `receivables_outpacing_revenue` — AR growth ~30% vs. revenue growth ~8%. **Expected**: one flag,
  `metric == "receivables_growth_vs_revenue_growth"`.
- `capex_spike_flagged` — capex/D&A jumps from ~1.2x to ~3x in the latest year. **Expected**: one
  flag, `metric == "capex_to_depreciation_ratio"`, latest fiscal year. (Resolving *why* is the
  Investigator's job in Phase 3 — this case only checks the flag gets raised.)
- `weak_cash_conversion` — CFO/NI ≈ 0.4, declining. **Expected**: flag on `cash_conversion_ratio`
  (and plausibly `sloan_accruals` — assert at least the former).
- `high_beneish_m_score` — two periods engineered (via `ratios.beneish_m_score` directly while
  drafting the fixture, iterating until M > -1.78) to trip the composite score. **Expected**: one
  flag, `metric == "beneish_m_score"`.
- `single_period_coverage_gap` — only one 10-K period (e.g., recent IPO). **Expected**:
  `flags == []`, and `coverage_gaps` contains an entry per growth/Beneish metric for that period
  with `reason == "no_prior_period_available"`.

**Evaluators, in preference order**:
1. **Deterministic — `FinancialStatementsGroundingEvaluator`**: every `Flag.source.value` traces
   exactly to the recomputed `RatioTrendBundle`. This is the hard gate; CLAUDE.md requires it at
   100%.
2. **Deterministic — numeric-prose check on `summary`**: best-effort regex extraction + tolerant
   match against the trend bundle's known values (raw fields, ratio values, and common derived
   transforms — ×100 for a percent, rounded integer for "N days"). Documented limitation: this
   can under-catch (a correctly-derived-but-differently-phrased number) but should not over-flag a
   genuinely grounded summary; tune tolerance generously rather than tightening it into false
   positives.
3. **Recall — per-case expected flags**: `Contains`-style check that the expected `(metric,
   fiscal_year)` pair is present in `flags`, and (for the clean case) `len(flags) == 0`.
4. **`LLMJudge`, used sparingly, only for `summary` quality** (per PRD's stated preference order —
   last resort): rubric — *"The summary is a specific, numeric interpretation of this company's
   own financial trend, not generic language that could describe any company in its sector. It
   does not characterize any coverage-gap-marked ratio as either healthy or concerning."*

**Trajectory evals**: not applicable — this agent has no tools/capabilities (PRD roster: "none");
trajectory evals are Investigator-only per PRD §8.

### Edge cases
- Zero 10-K periods after filtering (e.g., a ticker with only 10-Qs on file) — `compute_trend_bundle`
  should return `RatioTrendBundle(periods=[], ...)`, not raise; the agent then has nothing to
  interpret and should return `flag_candidates=[]` — add as a 7th eval case if time allows, at
  minimum cover it in `test_ratios_trend.py`.
- A `FlagCandidate` naming a real `(fiscal_year, fiscal_period)` but a metric whose `RatioResult.value`
  is `None` at that period (e.g., model raises a Beneish flag for the earliest period, where it's
  structurally unavailable) — must be dropped, covered by the plumbing test's scripted `FunctionModel`/`TestModel` case.
- Duplicate `FlagCandidate`s for the same metric/period — not deduplicated in this phase (Flag
  Consolidator's job is Phase 2, per PRD's pipeline diagram: "deterministic exact-dedup → Flag
  Consolidator" sits *after* this stage, across all three analysts). Note this explicitly so it
  isn't mistaken for a bug later.

---

## VALIDATION COMMANDS

### Level 1: Syntax & style
`uv run ruff check . && uv run pyright src tests`

### Level 2: Unit tests
`uv run pytest tests/unit -q` — must still pass at (49 existing + new) with **no**
`ANTHROPIC_API_KEY`/`LOGFIRE_TOKEN` set, confirming the phase didn't leak a live dependency into
CI-safe tests.

### Level 3: Evals
`ANTHROPIC_API_KEY=<real key> uv run python -m evals.financial_statements`
**Passing bar**: `FinancialStatementsGroundingEvaluator` at 100% across all cases (hard gate, no
exceptions per CLAUDE.md); recall check passes on all 6 cases including the zero-flag clean case;
`LLMJudge` summary-quality rubric passes on at least 5/6 (this one evaluator, being a judge, is
allowed to be the softest bar — document any failure rather than loosening the rubric, per
CLAUDE.md: "never delete or weaken an eval case to make a run pass").

### Level 4: Manual
Run against a real ticker end-to-end and inspect the Logfire trace:
```python
import asyncio
from agentic_fundamental_analyst.data.fetch import fetch_all
from agentic_fundamental_analyst.agents.financial_statements import run_financial_statements_analyst

async def main():
    financials, *_ = await fetch_all("GOOGL")
    result = await run_financial_statements_analyst(financials)
    print(result.model_dump_json(indent=2))

asyncio.run(main())
```
In the Logfire UI: confirm a `financial_statements_analyst_stage` span exists, tagged
`ticker="GOOGL"`, containing a nested `financial_statements_analyst` agent-run span with
`gen_ai.usage.*` and `operation.cost` attributes populated, and that `flag_count`/
`dropped_candidate_count` appear on the outer span.

### Level 5 (optional)
N/A — no `pipeline.py` to integrate against yet (lands Phase 5).

---

## ACCEPTANCE CRITERIA
- [ ] Contracts match this plan exactly (`SourcedFigure`, `Flag`, `Severity`, `PeriodRatios`,
      `RatioTrendBundle`, `FlagCandidate`, `FinancialAnalystAgentOutput`, `FinancialAnalystOutput`);
      no untyped boundary introduced
- [ ] All 5 validation levels pass (Level 5 N/A, documented as such)
- [ ] `FinancialStatementsGroundingEvaluator` at 100% — the deterministic groundedness gate
- [ ] Every `RatioResult(value=None, ...)` in a period's trend surfaces as a `CoverageGap` in
      `FinancialAnalystOutput.coverage_gaps`, never silently dropped
- [ ] Logfire trace shows the expected spans with `flag_count`/`dropped_candidate_count`/cost
      attributes, verified against a real run (Level 4)
- [ ] No regressions in the 49 existing Phase 0 unit tests
- [ ] `CLAUDE.md` Current State updated (mandatory every phase); `.agents/references/agents.md`
      and `observability.md` filled in from stub

## COMPLETION CHECKLIST
- [ ] Tasks executed in order, each validation passed immediately
- [ ] Full unit suite + the eval dataset pass
- [ ] Manual trace inspection done against a real ticker
- [ ] Plan file updated with an "Execution Deviations" section for anything that changed during
      implementation (mirroring `phase-0-data-layer.md`'s pattern), especially: the verified
      Anthropic model string, the verified `logfire.configure()` signature, and actual eval scores

## EXECUTION DEVIATIONS (actual, as built)

- **New, unplanned gotcha: `Agent('anthropic:...', ...)` requires `ANTHROPIC_API_KEY` at
  *construction* time, not `.run()` time.** `AnthropicProvider.__init__` validates the key eagerly
  inside `pydantic_ai.models.infer_model()`, which `Agent.__init__` calls synchronously. Since
  every agent module constructs its `Agent` at module import time, simply *importing*
  `agents.financial_statements` (required for the `TestModel` plumbing tests to override it) failed
  key-free. Fixed with a new `tests/conftest.py` that sets a placeholder, non-functional
  `ANTHROPIC_API_KEY` and `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` before test collection.
  No real credential involved, no network call possible even by mistake. Not anticipated by the
  plan; worth remembering for every future agent module.
- **Version floors confirmed and tightened**: `pydantic-ai>=2.32.0`, `logfire>=4.40.0`,
  `pydantic-evals>=2.32.0` (plan estimated `>=2.31.1` for the first two based on the dated research
  doc; bumped to what was actually current at implementation time, 2026-08-18). A single
  `pydantic-ai` dependency was sufficient — it bundles the Anthropic provider; no extras needed.
- **Model string confirmed, partially by inference**: `'claude-sonnet-5'` is directly present (as a
  non-deprecated literal) in pydantic-ai's `AnthropicModelName`. The combined `'anthropic:...'`
  prefixed form used in `agents/models.py` follows the standard `<provider>:<model>` convention but
  wasn't found as a literal string in source — flagged as inferred, not verified end-to-end,
  because no real `.run()` call has been made yet (blocked on a real API key). **Re-verify this is
  the first thing that happens once a key is available** — if wrong, it'll fail loudly and
  obviously at Level 4, not silently.
- **`send_to_logfire="if-token-present"` confirmed as a real, current `logfire.configure()`
  literal** (checked against `logfire/_internal/config.py`, v4.40.0). This let `observability.py`
  be simpler than the plan's sketch — no need for the `os.environ.get("LOGFIRE_TOKEN")` manual gate
  the plan proposed as a fallback; the library-native literal handles it.
- **`pyproject.toml`'s `[tool.pyright] include` extended to add `"evals"`** (plan's Level 1 command
  already said `pyright src tests evals`, but the config list itself wasn't updated to match until
  implementation — now consistent).
- **Eval case fixtures were numerically verified before being written**, not just estimated: every
  case's expected ratio values (DSO, receivables gap, capex/D&A, cash conversion ratio, and
  especially the Beneish M-Score composite) were computed directly via `ratios.py` functions during
  drafting and confirmed to cross (or not cross, for the clean case) the intended threshold —
  actual values are in code comments next to each fixture block. The Beneish case required real
  iteration (documented in the module) to land at M ≈ 0.80, comfortably above the -1.78 threshold.
- **`LLMJudge` defaults to an OpenAI model — real bug, fixed.** Every case crashed on Level 3's
  first run with `Set the OPENAI_API_KEY environment variable...`. `LLMJudge(rubric=...)` without
  an explicit `model=` doesn't inherit the agent's provider. Fixed by pinning
  `model=FINANCIAL_STATEMENTS_ANALYST_MODEL` explicitly in `evals/financial_statements.py`.
- **Levels 3 and 4 executed against real APIs once `ANTHROPIC_API_KEY` was provided.** Results:
  - Level 3 (eval run): `FinancialStatementsGroundingEvaluator`'s `flags_grounded` — **100% (6/6)**,
    the hard gate, as required. `ExpectedFlagsPresent` — **100% (6/6)**. `LLMJudge` — **4/6**,
    below the plan's stated 5/6 bar.
  - Level 4 (manual run against GOOGL, real EDGAR/FRED/Tiingo/Anthropic data): succeeded end to
    end; produced a real, sensible flag pattern — a 5-year escalating `capex_to_depreciation_ratio`
    flag sequence (2021: 2.40x → 2025: 4.33x), which is exactly the kind of real-world anomaly this
    system exists to eventually hand to the Investigator. Logfire trace confirmed at
    `https://logfire-us.pydantic.dev/aashikavishwanath/fundamental-analyst`: outer
    `financial_statements_analyst_stage` span (tagged `ticker`) → nested
    `financial_statements_analyst` agent-run span → `chat claude-sonnet-5` model-call span, plus
    `flag_count`/`dropped_candidate_count` attributes on the outer span, all as designed.
  - The model string `'anthropic:claude-sonnet-5'` — flagged as inferred-not-verified earlier in
    this doc — is now **confirmed working** via both of the above.
- **Two findings surfaced by live validation, deliberately left unresolved and flagged to the user
  rather than silently fixed**, per CLAUDE.md's "never quietly weaken/patch an eval or its result":
  1. **`LLMJudge` rubric ambiguity** — the 2 failing cases (`receivables_outpacing_revenue`,
     `capex_spike_flagged`) were flagged by the judge for "characterizing a coverage-gap-marked
     ratio as healthy," but inspection of the actual `coverage_gaps` field showed the gap applies
     only to the *first* period in each case (structurally gap-affected — no prior year exists to
     compute growth/Beneish ratios against), while the summary was correctly describing the
     *second* period's real, computed value for that same metric name. The rubric text doesn't
     scope "coverage-gap-marked" to a specific fiscal year, and the judge model over-generalized
     from metric name alone across both periods. This reads as a rubric-wording problem, not an
     analyst defect — the analyst's summaries were accurate. Undecided: reword the rubric to be
     explicitly period-scoped (e.g. "only for the exact fiscal_year+metric pairs listed in
     coverage_gaps"), or accept as a known `LLMJudge` limitation at this softest tier.
  2. **Duplicate `FiscalPeriod` rows in real EDGAR data (Phase 0-level, surfaced here)** — a live
     `fetch_all("GOOGL")` call returns 3 separate `FiscalPeriod` entries for
     `(fiscal_year=2015, fiscal_period="FY", form="10-K")`, confirmed directly by inspecting
     `bundle.periods`. `compute_trend_bundle()` silently assumed at most one entry per
     `(fiscal_year, fiscal_period, form)` — an assumption Phase 0's data layer doesn't actually
     guarantee. Observed effect: duplicated `CoverageGap` entries for 2015 in the output (cosmetic
     so far). Unresolved, more serious risk: since sort order among exact ties is not meaningfully
     defined here, pairing logic (`annual_periods[i-1]`) could nondeterministically select the
     wrong one of the three 2015 rows as 2016's "prior" period if the three actually carry
     different underlying values (e.g. one reflects a later restatement). Root cause (why
     `EdgarClient` produces 3 rows for one fiscal year) not investigated — could be amendment
     handling, multiple accession numbers reporting the same period, or a genuine dedup gap.
     Undecided: fix at the source in `EdgarClient` (Phase 0) or add defensive dedup in
     `compute_trend_bundle` (Phase 1) as a belt-and-suspenders measure regardless of root cause.
- **Both findings above were resolved after user sign-off, not left open.**
  1. **`LLMJudge` rubric reworded** to scope "coverage-gap-marked" to the exact fiscal year listed
     in `coverage_gaps` (the ambiguity was: the same metric name in a *different*, non-gap fiscal
     year is a real computed value and fair to characterize; the original rubric text didn't say
     so explicitly, and the judge over-generalized from metric name alone). Rerun after the reword:
     **`LLMJudge` 6/6** (up from 4/6) — `flags_grounded` and `ExpectedFlagsPresent` were unaffected
     (already 6/6, confirming the failures were genuinely rubric-side, not analyst-side).
  2. **What was originally reported as "3 duplicate `FiscalPeriod` rows for fiscal_year=2015" was
     re-diagnosed more precisely during investigation**: every `period_end` in the data is actually
     unique — there's no true duplication. The real bug is that 2 of the 3 periods (`period_end`
     2013-12-31 and 2014-12-31) were mislabeled `fiscal_year=2015`, because `EdgarClient`'s
     "earliest-filed occurrence is authoritative for fy/fp" heuristic assumed the earliest filing to
     report a period would always be that period's own original 10-K — false when that period's own
     filing isn't independently observed in the fetched concept history, leaving only a *later*
     filing's prior-year comparative column (which inherits that later filing's own `fy` stamp) as
     the sole observation. **Fixed in `edgar.py`**: added `_COMPARATIVE_COLUMN_FILING_LAG_DAYS = 120`
     — if the earliest-filed occurrence of a `form == "10-K"` period arrived more than 120 days after
     `period_end`, its `fiscal_year` is derived from `period_end.year` instead (safe for annual/FY
     periods; deliberately not extended to 10-Qs, where non-calendar fiscal-year filers make that
     inference unsafe). Verified against both GOOGL and AAPL after a cache-cleared refetch: every
     `fiscal_year` now exactly equals `period_end.year`, no exceptions.
  3. **A second, more consequential `EdgarClient` bug was found while verifying fix #2 against a
     second real ticker (AAPL)**, not anticipated by either the plan or the original finding: many
     10-Ks (pre-~2020, when the SEC required it) include a "Selected Quarterly Financial Data"
     footnote — quarterly revenue/net income for the past two years, disclosed *inside* the 10-K
     document. When XBRL-tagged, each quarter's duration fact still carries `form="10-K"` (it's
     literally in that filing) despite a ~90-day duration, not a full fiscal year. Nothing in the
     original loop validated duration length before accepting a fact into `periods_by_key` — so each
     quarterly footnote entry became its own spurious "annual" period once `compute_trend_bundle`'s
     `form == "10-K"` filter (a Phase 1 assumption) treated it as a genuine fiscal year. Confirmed via
     raw SEC data: 66 spurious `net_income` points and 6 spurious `revenue` points for AAPL, all
     `form="10-K"`; confirmed **absent** for GOOGL, which is exactly why this phase's original
     GOOGL-only Level 4 validation didn't catch it. **Fixed in `edgar.py`**: added
     `_ANNUAL_DURATION_DAYS_RANGE = (350, 380)` — a duration-type fact with `form == "10-K"` is now
     rejected unless its `(end - start).days` falls in that range. This also incidentally fixes a
     latent, worse variant of the same bug: without the length check, the pre-existing
     "shortest-duration-wins" tiebreak (Phase 0's own dedup logic) would have *preferred* a
     quarterly-footnote fact over the true annual fact whenever their `end` dates coincided (i.e. the
     filer's Q4 typically ends on the fiscal year-end date), silently corrupting the year's own
     annual figure, not just adding spurious extra periods. Verified after a cache-cleared refetch:
     AAPL now returns exactly 19 clean annual periods (2007-2025, `fiscal_year == period_end.year`
     for all), GOOGL exactly 13 (2013-2025) — zero mislabeled or spurious periods in either. Full
     unit suite (58 tests, including all existing `EdgarClient` golden-file tests) still passes with
     no regressions.
  - **End-to-end re-verification after both `EdgarClient` fixes**: reran the Financial Statements
    Analyst against AAPL (previously untested end-to-end in this phase) — zero flags on AAPL's
    genuinely clean 19-year history, zero dropped candidates, a specific and accurate summary citing
    real numbers (cash conversion consistently >1.0x, small negative Sloan accruals throughout,
    capex/D&A declining then re-rising). GOOGL rerun unaffected (its data was already clean before
    these fixes; the 2015 mislabel fix changed its `2013FY`/`2014FY` citations from "2015FY" to the
    correct year, otherwise identical behavior).
- **Final status**: all 4 validation levels green, all findings from live validation resolved (not
  deferred) with user sign-off at each decision point, no known open issues from this phase's scope.
  Two Phase 0 `EdgarClient` bugs fixed as a direct result of Phase 1's live validation — a concrete
  instance of PRD §9's annotation-to-fix flywheel, just one phase earlier than transcripts/traces
  usually trigger it.

## NOTES
- **Cost**: `RatioTrendBundle` for ~5 years is a few KB of JSON — expect low four-figure input
  tokens and a few hundred output tokens per run on Sonnet. This is a small fraction of the PRD's
  ~$2/run full-pipeline ceiling; no tier-downgrade justification expected from this phase alone.
- **Deferred to Phase 2**: quarterly trend analysis, checklist items #8–17, cross-analyst flag
  deduplication/consolidation (`ConsolidatedFlag` is intentionally not defined yet — no consumer
  exists for it until the Flag Consolidator).
- **Deferred to a later refactor**: if the Filings/Transcript analysts (Phase 2) turn out to need
  the same grounding-evaluator shape as `FinancialStatementsGroundingEvaluator`, generalize it
  into a shared `evals/evaluators.py::GroundingEvaluator` then — building that abstraction now,
  from a single instance, would be guessing at the wrong shape.
- **Open risk flagged, not resolved, by this plan**: the coarser `SourcedFigure.source` string
  (vs. the PRD's XBRL-tag-level sketch) is a real fidelity loss for the eventual memo's Appendix
  section (§3 Section 10), which wants filing-level citations. Not fixed here because it would
  require re-threading tag/accession provenance through `ratios.py`'s pure-float interface — a
  Phase 0 boundary this phase shouldn't reopen unilaterally. Flag for the user before Phase 5
  (Synthesizer/Appendix) if it hasn't been revisited by then.
