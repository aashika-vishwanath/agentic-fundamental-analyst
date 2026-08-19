# CLAUDE.md

## Project Overview

Given a US-listed, SEC-filing, non-financial operating company ticker, this system produces a grounded investment memo with a Buy/Hold/Sell recommendation. Architecture: a fixed deterministic pipeline (plain async Python) with agentic islands — single-shot document-grounded agents for interpretation, and exactly one real agentic loop (the Investigator, with web search) for anomaly investigation. Full detail, rationale, and the complete agent/data/phase spec: **`PRD.md`** — this file is constraints and pointers only, never a substitute for it.

Status: Phase 0 complete. `pyproject.toml` exists (uv-managed); `src/agentic_fundamental_analyst/` has the full deterministic data layer. The Conventions section below now reflects code that exists, not just a plan.

---

## Current State

**Last completed phase**: Phase 0 — deterministic data layer. `EdgarClient` (submissions, XBRL concepts w/ tag-alias fallback, filing-section extraction, SIC intake), `FredClient`, `PriceClient` (Tiingo only — see below), the cache layer, `ratios.py` (full earnings-quality checklist incl. all 8 Beneish components), `valuation.py` (DCF bull/base/bear, peer multiples), and `fetch_all(ticker)` are all built and live-verified against real tickers (GOOGL, AAPL, JPM, O, MET).
**Known Phase 0 gaps** (see `.agents/plans/phase-0-data-layer.md`'s Execution Deviations for full detail):
- **Stooq is blocked, not implemented** — its CSV endpoint now requires solving a JS proof-of-work challenge (bot-detection change since it was researched). `PriceClient` wraps Tiingo only; `data/stooq.py` is a documented stub. Not a blocker (Stooq was always the backfill fallback, not primary).
- **`cash_conversion_cycle()` is a permanent coverage gap** — `FiscalPeriod` has no `accounts_payable` field, so the DPO leg can never compute.
- `FiscalPeriod` was extended 5 fields beyond the PRD's illustrative sketch (`cost_of_revenue`, `sga_expense`, `current_assets`, `ppe_gross`, `total_debt`) to support the full 8-component Beneish M-Score.
**In progress / next up**: Phase 1 — first analyst (Financial Statements Analyst) end-to-end, with Logfire wired in from this phase onward.
**Eval datasets passing**: none yet (Phase 0 has no LLM output; golden-file/unit tests are the phase-appropriate substitute — 49 tests passing, 100% network-free and key-free).
**Logfire wired up**: not yet (starts Phase 1).

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

**Layout** (Phase 0 built; `agents/`, `evals/`, `pipeline.py` land in later phases):
```
src/agentic_fundamental_analyst/
  config.py       # loads .env once at import time (FRED_KEY, TIINGO_KEY, EDGAR_USER_AGENT)
  data/           # EdgarClient, FredClient, PriceClient, cache layer, filing_sections.py, fetch_all()
  contracts/      # Pydantic models — financials, filings, macro, prices, intake, ratios, valuation
  agents/         # not yet built (Phase 1+) — one module per agent role, exports a named Agent instance
  ratios.py       # deterministic ratio math (DSO, Sloan accruals, cash conversion, Beneish x8, etc.)
  valuation.py    # deterministic DCF/comps math
  pipeline.py     # not yet built (Phase 5) — run_memo_pipeline(ticker), the orchestrator
evals/            # not yet built — Pydantic Evals Datasets, one file per agent
tests/
  unit/           # network-free unit tests (respx-mocked), 49 passing
  golden/         # golden-file fixtures (JSON API responses + trimmed real filing HTML)
```
- **Contracts** live in `contracts/`, one module per logical group (flags, verdicts, memo). No model is defined inline inside an agent module.
- **Agent definition pattern**: one `Agent` instance per module in `agents/`, named for its role (e.g. `agents/financial_statements.py` exports `financial_statements_analyst`). Model tier per agent is set from a shared config/constants module, never hardcoded per call site, so routing changes (per PRD §10) touch one place.
- **Prompts**: use `instructions=` over `system_prompt=` (instructions aren't replayed from `message_history` — see `.agents/references/pydantic-ai-v2.md`). Cache-friendly ordering: stable, long-lived content (filing text, the financial statement bundle) goes first in context.
- **Eval datasets**: one `Dataset` per agent in `evals/`, cases named for the scenario they cover (e.g. `capex_spike_benign`, `capex_spike_concerning`, `transcript_unavailable_gap`), not for the mechanism being tested.
- **Golden files**: `tests/golden/<ticker>_<fixture_type>.{json,html}`, sourced from real captured API/filing responses (trimmed for size where needed, verified the trim doesn't change parsed output), never hand-constructed.

---

## Commands

All verified working as of Phase 0.

- **Data-layer unit tests** (network-free, key-free — the CI-safe suite): `uv run pytest tests/unit -q`
- **Lint**: `uv run ruff check .`
- **Type-check**: `uv run pyright src tests`
- **Clear the disk cache** (force fresh fetches): `uv run python -c "from agentic_fundamental_analyst.data.cache import clear_cache; clear_cache()"`
- **Fetch one ticker live** (requires real `FRED_KEY`/`TIINGO_KEY` in `.env`):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  asyncio.run(fetch_all("GOOGL"))
  ```
- **Run the pipeline for one ticker**: not yet available — `pipeline.py`/`run_memo_pipeline()` land in Phase 5.
- **Run a single agent's eval dataset / all evals**: not yet available — no agents exist yet (Phase 1+).

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
- **EDGAR client**: `src/agentic_fundamental_analyst/data/edgar.py` — see `.agents/references/data-layer.md` for the two non-obvious XBRL merge bugs found and fixed here.
- **Filing HTML parsing**: `src/agentic_fundamental_analyst/data/filing_sections.py` — bold/non-hyperlinked "Item N." heuristic, validated against two filers with different HTML conventions.
- **Ratio/valuation math**: `src/agentic_fundamental_analyst/ratios.py`, `valuation.py`.
- **Pipeline entry point, agent registry, eval directory**: not yet created — land in Phase 1+.

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

`data-layer.md`, `free-data-sources.md`, and `valuation.md` are now filled in (Phase 0). `agents.md`, `evals.md`, `observability.md` remain stubs — fill each in as its phase is built.
