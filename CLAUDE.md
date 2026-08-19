# CLAUDE.md

## Project Overview

Given a US-listed, SEC-filing, non-financial operating company ticker, this system produces a grounded investment memo with a Buy/Hold/Sell recommendation. Architecture: a fixed deterministic pipeline (plain async Python) with agentic islands — single-shot document-grounded agents for interpretation, and exactly one real agentic loop (the Investigator, with web search) for anomaly investigation. Full detail, rationale, and the complete agent/data/phase spec: **`PRD.md`** — this file is constraints and pointers only, never a substitute for it.

Status: Phase 1 implemented and live-validated against a real ticker (GOOGL) and a real Anthropic model; two real findings surfaced during that validation are open for a decision (see Current State) before the phase is fully closed. `pyproject.toml` exists (uv-managed); `src/agentic_fundamental_analyst/` has the full deterministic data layer plus the first agent. The Conventions section below now reflects code that exists, not just a plan.

---

## Current State

**Last completed phase**: Phase 1 — Financial Statements Analyst. Code-complete, all 4 validation levels executed and green, both real bugs found during live validation root-caused and fixed (not deferred). `EdgarClient` (Phase 0) now emits cleaner data as a result — see below.
- **New contracts**: `contracts/sourcing.py` (`SourcedFigure`), `contracts/flags.py` (`Severity`, `Flag` — generic, reused by later analysts), `contracts/financial_analyst.py` (`FlagCandidate`, `FinancialAnalystAgentOutput`, `FinancialAnalystOutput`), `contracts/ratios.py` extended with `PeriodRatios`/`RatioTrendBundle`.
- **New deterministic layer**: `ratios.compute_period_ratios()` / `compute_trend_bundle()` — turns `FinancialStatementBundle` into `RatioTrendBundle`, annual (10-K) periods only. Deliberately **not** quarterly yet — see Known Gaps below on why 10-Q periods aren't safe to include today.
- **First agent**: `agents/financial_statements.py` — `financial_statements_analyst` (Claude Sonnet, single-shot, no tools) plus `run_financial_statements_analyst()`. Grounding is enforced structurally: the agent's own output type never carries a numeric value, only `(metric, fiscal_year, fiscal_period)` candidates; deterministic code looks up the real value and drops anything that doesn't resolve. Live-verified against GOOGL and AAPL — sensible summaries, correctly zero flags on AAPL's genuinely clean history, correctly escalating capex-intensity flags on GOOGL's real 2021-2025 buildout, zero dropped candidates in both. See `.agents/plans/phase-1-financial-statements-analyst.md` for full design rationale.
- **Logfire wired up**: yes. `observability.py` calls `logfire.configure(send_to_logfire="if-token-present")` + `logfire.instrument_pydantic_ai()` at import time; confirmed safe to import with zero env vars set, and confirmed producing real traces at `https://logfire-us.pydantic.dev/aashikavishwanath/fundamental-analyst` (`financial_statements_analyst_stage` span → nested `financial_statements_analyst` agent-run span → `chat claude-sonnet-5` model-call span).
- **Model string confirmed working**: `'anthropic:claude-sonnet-5'` made real, successful calls throughout — the plan's flagged unverified-string risk is resolved.
- **Eval dataset**: `evals/financial_statements.py`, 6 cases (`clean_financials_no_flags`, `receivables_outpacing_revenue`, `capex_spike_flagged`, `weak_cash_conversion`, `high_beneish_m_score`, `single_period_coverage_gap`), each with hand-verified expected ratio values. **Final run against the real model: 6/6 on all three evaluators** — `flags_grounded` (hard gate), `ExpectedFlagsPresent` (recall), and `LLMJudge` (summary quality) all 100%.
- **Two implementation gotchas found and fixed, not anticipated in the plan**: (1) `pydantic_ai.Agent('anthropic:...', ...)` eagerly validates `ANTHROPIC_API_KEY` at *construction* time, not `.run()` time — fixed via `tests/conftest.py` (placeholder key + `ALLOW_MODEL_REQUESTS = False`, no real network call possible in `tests/unit`). (2) `pydantic_evals.evaluators.LLMJudge` defaults to an OpenAI model — fixed by pinning `model=FINANCIAL_STATEMENTS_ANALYST_MODEL` explicitly.
- **One eval-quality fix, applied after user sign-off**: the `LLMJudge` summary-quality rubric was ambiguous about *which fiscal year* a coverage gap applies to, causing 2/6 false-negative judgments (the judge over-generalized "this metric had a gap in an earlier period" to "never characterize this metric name at all"). Reworded to scope "coverage-gap-marked" to the exact fiscal year listed — confirmed 6/6 after the reword. Not silently patched — flagged to the user with the diagnosis first.
- **Two real `EdgarClient` (Phase 0) bugs found via this phase's live validation, root-caused and fixed, not deferred**:
  1. **Comparative-column `fiscal_year` mislabeling.** A 10-K's prior-year comparative income-statement columns (e.g. a FY2015 10-K showing FY2013/FY2014 for comparison) inherit that filing's own `fy` XBRL stamp when the period's own original filing isn't otherwise observed in the fetched data — so GOOGL's 2013/2014 periods were coming back labeled `fiscal_year=2015`. Fixed: for `form == "10-K"`, if the earliest-filed occurrence of a period arrived >120 days after `period_end` (too late to be that period's own filing), `fiscal_year` is derived from `period_end.year` instead of trusting the inherited `fy` stamp. Confirmed: every GOOGL/AAPL 10-K period's `fiscal_year` now exactly matches `period_end.year`.
  2. **Quarterly-footnote contamination.** Pre-~2020, many 10-Ks included a "Selected Quarterly Financial Data" footnote; when XBRL-tagged, each quarter's revenue/net_income fact still carries `form="10-K"` despite a ~90-day duration, so `compute_trend_bundle`'s `form == "10-K"` filter was silently treating each quarterly footnote entry as its own spurious annual period. Confirmed present in real AAPL data (66 spurious `net_income` points, 6 spurious `revenue` points) — confirmed absent in GOOGL's, which is why GOOGL-only validation didn't catch it. Fixed: duration-type facts with `form == "10-K"` are now rejected unless their duration is 350-380 days. Verified: AAPL now returns exactly 19 clean annual periods (2007-2025), GOOGL exactly 13 (2013-2025), both with zero mislabeled/spurious periods.
**Known Phase 0 gaps** (see `.agents/plans/phase-0-data-layer.md`'s Execution Deviations for full detail):
- **Stooq is blocked, not implemented** — its CSV endpoint now requires solving a JS proof-of-work challenge (bot-detection change since it was researched). `PriceClient` wraps Tiingo only; `data/stooq.py` is a documented stub. Not a blocker (Stooq was always the backfill fallback, not primary).
- **`cash_conversion_cycle()` is a permanent coverage gap** — `FiscalPeriod` has no `accounts_payable` field, so the DPO leg can never compute.
- `FiscalPeriod` was extended 5 fields beyond the PRD's illustrative sketch (`cost_of_revenue`, `sga_expense`, `current_assets`, `ppe_gross`, `total_debt`) to support the full 8-component Beneish M-Score.
- **10-Q periods cannot safely enter ratio-trend math yet** (found in Phase 1). `EdgarClient`'s duration de-dup (`data-layer.md` "bug #2") picks the shortest available reporting window per concept, but cash-flow-statement lines are frequently tagged YTD-only in 10-Qs with no discrete-quarter figure ever filed — so a `FiscalPeriod` for a 10-Q can end up with `operating_cash_flow` as a 9-month cumulative figure sitting next to a true single-quarter `net_income`, with nothing on the model recording the mismatch. This would silently corrupt `cash_conversion_ratio` and `sloan_accruals` for interior quarters. `compute_trend_bundle()` filters to `form == "10-K"` specifically because of this — not just to reduce Phase 1 scope. Needs a duration marker on `FiscalPeriod` before quarterly trend analysis is safe.
- **`get_financial_statement_bundle`'s comparative-column and quarterly-footnote handling** — both fixed in Phase 1 (see above); the two `EdgarClient` bugs listed there predate Phase 1 but were only surfaced by it, so noting here for future readers grepping Phase 0 gaps specifically.
**Next up**: Phase 2 — Filings Analyst, Transcript Analyst, Flag Consolidator.
**Eval datasets passing**: `evals/financial_statements.py` — **6/6 on all three evaluators** (`flags_grounded`, `ExpectedFlagsPresent`, `LLMJudge`) against the real model. Unit/plumbing tests: **58 passing**, 100% network-free and key-free (49 from Phase 0 + 5 ratio-trend + 4 agent-plumbing).
**Logfire wired up**: yes — confirmed producing real traces (see above).

This section is mandatory and unconditional to update — `/execute` must update it at the end of every phase/feature, regardless of whether any convention changed (see `execute.md` Final Verification). `/prime` cross-checks it against `git log`/`git status` rather than trusting it blindly, but it should never be allowed to go stale.

---

## Hard Constraints

Never violate these. If a task seems to require violating one, stop and flag it rather than working around it.

- **Agents interpret; deterministic code fetches and computes.** Never wrap an API call, filing parse, ratio calculation, or valuation calculation in an agent.
- **Every inter-stage boundary is a typed Pydantic model.** Never pass a `dict` between pipeline stages.
- **No new agent or prompt change ships without its labeled eval dataset passing.** Built alongside the feature, not after.
- **Never delete or weaken an eval case to make a run pass.** If a case seems wrong, flag it to the user — don't quietly loosen it.
- **`coverage_gaps` must propagate explicitly.** Missing data (no transcript, no XBRL tag match, excluded sector) is never coerced into a bullish or bearish signal.
- **Every quantitative claim in LLM output must trace to a field in its typed input**, checked deterministically by the `GroundingEvaluator` — never by an LLM judge.
- **No API keys in code.** Environment variables only (EDGAR needs none but requires a descriptive `User-Agent`; FRED and Tiingo need free keys).
- **The pipeline is fixed.** No orchestrator/router agent, no dynamic stage routing — every run executes every stage.
- **The Investigator is the only agentic loop and the only agent with `WebSearch`/`WebFetch`.** Every other agent is single-shot.
- **Excluded sectors (banks, insurers, REITs) are rejected at data-layer intake via SIC code**, before any agent runs — never inside an agent.

---

## Conventions

**Layout** (Phase 0 + Phase 1 built; `pipeline.py` lands in Phase 5):
```
src/agentic_fundamental_analyst/
  config.py       # loads .env once at import time (FRED_KEY, TIINGO_KEY, EDGAR_USER_AGENT, ANTHROPIC_API_KEY, LOGFIRE_TOKEN)
  observability.py # Logfire bring-up (logfire.configure + instrument_pydantic_ai), import-time, token-optional
  data/           # EdgarClient, FredClient, PriceClient, cache layer, filing_sections.py, fetch_all()
  contracts/      # Pydantic models — financials, filings, macro, prices, intake, ratios, valuation, sourcing, flags, financial_analyst
  agents/         # models.py (model-tier constants) + one module per agent role, exports a named Agent instance
    financial_statements.py  # first agent: financial_statements_analyst, run_financial_statements_analyst()
  ratios.py       # deterministic ratio math (DSO, Sloan accruals, cash conversion, Beneish x8, trend computation)
  valuation.py    # deterministic DCF/comps math
  pipeline.py     # not yet built (Phase 5) — run_memo_pipeline(ticker), the orchestrator
evals/            # Pydantic Evals Datasets, one file per agent — financial_statements.py is the first
tests/
  conftest.py     # sets a placeholder ANTHROPIC_API_KEY + ALLOW_MODEL_REQUESTS=False before collection (see Current State gotcha)
  unit/           # network-free unit tests (respx-mocked + TestModel), 58 passing
  golden/         # golden-file fixtures (JSON API responses + trimmed real filing HTML)
```
- **Contracts** live in `contracts/`, one module per logical group (flags, verdicts, memo). No model is defined inline inside an agent module.
- **Agent definition pattern**: one `Agent` instance per module in `agents/`, named for its role (e.g. `agents/financial_statements.py` exports `financial_statements_analyst`). Model tier per agent is set from a shared config/constants module, never hardcoded per call site, so routing changes (per PRD §10) touch one place.
- **Prompts**: use `instructions=` over `system_prompt=` (instructions aren't replayed from `message_history` — see `.agents/references/pydantic-ai-v2.md`). Cache-friendly ordering: stable, long-lived content (filing text, the financial statement bundle) goes first in context.
- **Eval datasets**: one `Dataset` per agent in `evals/`, cases named for the scenario they cover (e.g. `capex_spike_benign`, `capex_spike_concerning`, `transcript_unavailable_gap`), not for the mechanism being tested.
- **Golden files**: `tests/golden/<ticker>_<fixture_type>.{json,html}`, sourced from real captured API/filing responses (trimmed for size where needed, verified the trim doesn't change parsed output), never hand-constructed.

---

## Commands

All verified working, including live runs against real APIs (Phase 0) and a real Anthropic model (Phase 1).

- **Unit + plumbing tests** (network-free, key-free — the CI-safe suite, includes `TestModel`-based agent tests): `uv run pytest tests/unit -q`
- **Lint**: `uv run ruff check .`
- **Type-check**: `uv run pyright src tests evals`
- **Clear the disk cache** (force fresh fetches): `uv run python -c "from agentic_fundamental_analyst.data.cache import clear_cache; clear_cache()"`
- **Fetch one ticker live** (requires real `FRED_KEY`/`TIINGO_KEY` in `.env`):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  asyncio.run(fetch_all("GOOGL"))
  ```
- **Run the Financial Statements Analyst on one ticker** (requires real `FRED_KEY`/`TIINGO_KEY`/`ANTHROPIC_API_KEY` in `.env`; live-verified against GOOGL):
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
- **Run the Financial Statements Analyst's eval dataset** (requires real `ANTHROPIC_API_KEY`; live-verified — `flags_grounded`/`ExpectedFlagsPresent` 100%, `LLMJudge` 4/6, see Current State): `uv run python -m evals.financial_statements`
- **Logfire auth** (one-time, interactive — run yourself, not scriptable): `uv run logfire auth`, then `uv run logfire projects new` (or `use`)
- **Run the pipeline for one ticker**: not yet available — `pipeline.py`/`run_memo_pipeline()` land in Phase 5.

Do not fabricate commands beyond what's listed here — a stale or invented command is worse than an empty section.

---

## Testing Strategy

Layered, bottom-up — see PRD §8 for full detail:
1. Golden-file unit tests (data layer) — no LLM involved.
2. Per-agent Pydantic Evals datasets — required before an agent ships.
3. Trajectory evals (Investigator only) — `HasMatchingSpan` checks it actually searched.
4. End-to-end groundedness/consistency evals — the `GroundingEvaluator` plus the two canonical capex-spike golden cases.

**Evaluator preference, always in this order**: deterministic check > recall check (`Contains`, `IsInstance`, set comparison) > `LLMJudge`/`GEval`. Reach for a judge only when no deterministic or recall check can substitute.

**CI**: `TestModel`/`FunctionModel` plumbing tests only — zero API spend. LLM eval runs are on-demand, not a CI gate, until cost/latency budgets are established in Phase 6.

---

## Observability & Logging Strategy

- Logfire instrumented from Phase 1 onward (`logfire.instrument_pydantic_ai()`), not deferred to later phases.
- One trace per pipeline run; `ticker` attached as a baggage attribute so every span in the trace is filterable by it.
- Every agent gets `name=` for identifiable spans; every pipeline stage (agent or deterministic) gets cost/signal attributes (flag counts, verdict, tool-call count).
- Check traces whenever: an eval regresses, a cost anomaly appears, or you disagree with a real output — the last case should turn into a new eval case (PRD §9's annotation flywheel), not just a one-off fix.

---

## Key Files

- **Data fetch entry point**: `src/agentic_fundamental_analyst/data/fetch.py` (`fetch_all(ticker)`) — gated on `TickerIntakeResult.in_scope`, raises `TickerOutOfScope` for excluded sectors before any other fetch.
- **Contracts**: `src/agentic_fundamental_analyst/contracts/` — `financials.py`, `filings.py`, `macro.py`, `prices.py`, `intake.py`, `ratios.py`, `valuation.py`.
- **EDGAR client**: `src/agentic_fundamental_analyst/data/edgar.py` — see `.agents/references/data-layer.md` for the four non-obvious XBRL merge bugs found and fixed here (2 from Phase 0, 2 more surfaced by Phase 1's live validation).
- **Filing HTML parsing**: `src/agentic_fundamental_analyst/data/filing_sections.py` — bold/non-hyperlinked "Item N." heuristic, validated against two filers with different HTML conventions.
- **Ratio/valuation math**: `src/agentic_fundamental_analyst/ratios.py` (incl. `compute_trend_bundle` — annual-only, see Current State gap note), `valuation.py`.
- **First agent**: `src/agentic_fundamental_analyst/agents/financial_statements.py` (`financial_statements_analyst`, `run_financial_statements_analyst`) — grounding is enforced structurally; see `.agents/plans/phase-1-financial-statements-analyst.md` for why the agent's own output type never carries a numeric value.
- **Logfire bring-up**: `src/agentic_fundamental_analyst/observability.py`.
- **Eval dataset**: `evals/financial_statements.py`.
- **Pipeline entry point**: not yet created — lands in Phase 5.

---

## On-Demand Context

| When working on... | Read first |
|---|---|
| Pydantic AI v2 capabilities, evals, TestModel, Logfire integration | `.agents/references/pydantic-ai-v2.md` |
| Free data source APIs (EDGAR, FRED, Tiingo/Stooq) — endpoints, rate limits, gotchas | `.agents/references/free-data-sources.md` |
| Our data layer code — clients, cache, parsing (not the raw APIs themselves) | `.agents/references/data-layer.md` |
| Any agent's prompt design or output contract | `.agents/references/agents.md` |
| Eval datasets or evaluators | `.agents/references/evals.md` |
| Logfire spans, dashboards, annotation workflow | `.agents/references/observability.md` |
| Valuation math (DCF, comps) | `.agents/references/valuation.md` |
| Memo section structure, earnings-quality checklist, MVP section availability | `.claude/skills/investment-memo-writing/SKILL.md` |

`data-layer.md`, `free-data-sources.md`, `valuation.md` (Phase 0), `agents.md`, and `observability.md` (Phase 1) are now filled in. `evals.md` remains a stub — fill in once evals have actually been run (currently blocked on a real `ANTHROPIC_API_KEY`; see Current State).
