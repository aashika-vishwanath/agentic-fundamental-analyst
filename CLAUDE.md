# CLAUDE.md

## Project Overview

Given a US-listed, SEC-filing, non-financial operating company ticker, this system produces a grounded investment memo with a Buy/Hold/Sell recommendation. Architecture: a fixed deterministic pipeline (plain async Python) with agentic islands — single-shot document-grounded agents for interpretation, and exactly one real agentic loop (the Investigator, with web search) for anomaly investigation. Full detail, rationale, and the complete agent/data/phase spec: **`PRD.md`** — this file is constraints and pointers only, never a substitute for it.

Status: Phases 0, 1, and 2 complete and tested. `pyproject.toml` exists (uv-managed); `src/agentic_fundamental_analyst/` has the full deterministic data layer plus four agents (Financial Statements, Filings, Transcript Analysts + Flag Consolidator). The Conventions section below reflects code that exists, not just a plan.

---

## Current State

**Completed**: Phase 0 (deterministic data layer), Phase 1 (Financial Statements Analyst), Phase 2 (Filings Analyst, Transcript Analyst, Flag Consolidator). All built, tested, and live-verified — no known regressions or open issues.
- Data layer: `EdgarClient`, `FredClient`, `PriceClient`, cache, `ratios.py`, `valuation.py`, `fetch_all()` (now returns a 5-tuple incl. `TranscriptInput | None`). `get_filing_sections()` now scans up to 12 recent 8-Ks (not just the latest) and a new `get_transcript_input()` discovers transcript exhibits via each 8-K's own file index — detail in `.agents/references/data-layer.md`.
- Agents: `financial_statements.py` (Phase 1), `filings.py`/`transcript.py`/`flag_consolidator.py` (Phase 2). Two grounding mechanisms beyond Phase 1's numeric-table lookup: verbatim quoted-evidence substring checking (`agents/grounding.py`, prose input) for Filings/Transcript, and index-into-a-closed-list checking for the Consolidator. `Flag.source` is now `SourcedFigure | SourcedQuote`. Full rationale in `.agents/plans/phase-2-filings-transcript-consolidator.md`.
- Logfire wired up and confirmed producing real traces for all four agents, incl. confirming the Transcript Analyst emits **no** span/model-call when no transcript is found (a structural guarantee, not an instructed one).
**Known permanent gaps**: Stooq blocked (Tiingo-only pricing); `cash_conversion_cycle()` can't compute; 10-Q periods excluded from ratio-trend math; Filings Analyst checklist items #9/#14 only partially covered (single-filing visibility only, Item 8 audit opinion not parsed); DEF 14A/Forms 3/4/5 (checklist #10/#16) out of scope. Detail in `data-layer.md` and the Phase 2 plan.
**Cost note**: Filings Analyst is meaningfully more expensive per call than the other three agents (~$0.13–$0.28 real-GOOGL cost, 65K-132K input tokens — a large 10-K's prose is much bigger than Phase 1's ratio JSON). No truncation built yet; watch this against the PRD's ~$2/run ceiling once Phase 5 wires the full pipeline.
**Tests**: 89 unit tests passing (network-free, key-free). Eval datasets, all live-verified against the real model: `evals/financial_statements.py` 6/6 all evaluators; `evals/filings.py` 6/6 all evaluators; `evals/transcripts.py` grounding+recall 3/3, LLMJudge 2/3 (see Phase 2 plan's Execution Deviations — likely single-sample judge noise on an otherwise well-grounded summary, not re-tuned to force a pass); `evals/flag_consolidator.py` 3/3 (no judge — fully deterministic+recall).
**Next up**: Phase 3 — the Investigator (the system's one agentic loop).

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

**Layout** (Phase 0 + 1 + 2 built; `pipeline.py` lands in Phase 5):
```
src/agentic_fundamental_analyst/
  config.py       # loads .env once at import time (FRED_KEY, TIINGO_KEY, EDGAR_USER_AGENT, ANTHROPIC_API_KEY, LOGFIRE_TOKEN)
  observability.py # Logfire bring-up (logfire.configure + instrument_pydantic_ai), import-time, token-optional
  data/           # EdgarClient, FredClient, PriceClient, cache layer, filing_sections.py, fetch_all()
  contracts/      # Pydantic models — financials, filings, macro, prices, intake, ratios, valuation, sourcing, flags,
                  # financial_analyst, transcripts, filings_analyst, transcript_analyst, consolidation
  agents/         # models.py (model-tier constants) + grounding.py (shared quote-grounding) + one module per agent role
    financial_statements.py  # Phase 1: financial_statements_analyst, run_financial_statements_analyst()
    filings.py                # Phase 2: filings_analyst, run_filings_analyst(ticker, sections)
    transcript.py               # Phase 2: transcript_analyst, run_transcript_analyst(ticker, transcript | None)
    flag_consolidator.py         # Phase 2: flag_consolidator, run_flag_consolidator(all_flags)
  flags.py        # deterministic exact-dedup (deduplicate_exact_flags) — Phase 2, sibling to ratios.py/valuation.py
  ratios.py       # deterministic ratio math (DSO, Sloan accruals, cash conversion, Beneish x8, trend computation)
  valuation.py    # deterministic DCF/comps math
  pipeline.py     # not yet built (Phase 5) — run_memo_pipeline(ticker), the orchestrator
evals/            # Pydantic Evals Datasets, one file per agent, plus grounding.py (shared quote-grounding check)
tests/
  conftest.py     # sets a placeholder ANTHROPIC_API_KEY + ALLOW_MODEL_REQUESTS=False before collection (see Current State gotcha)
  unit/           # network-free unit tests (respx-mocked + TestModel), 89 passing
  golden/         # golden-file fixtures (JSON API responses + trimmed real filing HTML)
```
- **Contracts** live in `contracts/`, one module per logical group (flags, verdicts, memo). No model is defined inline inside an agent module.
- **Agent definition pattern**: one `Agent` instance per module in `agents/`, named for its role (e.g. `agents/financial_statements.py` exports `financial_statements_analyst`). Model tier per agent is set from a shared config/constants module, never hardcoded per call site, so routing changes (per PRD §10) touch one place.
- **Prompts**: use `instructions=` over `system_prompt=` (instructions aren't replayed from `message_history` — see `.agents/references/pydantic-ai-v2.md`). Cache-friendly ordering: stable, long-lived content (filing text, the financial statement bundle) goes first in context.
- **Eval datasets**: one `Dataset` per agent in `evals/`, cases named for the scenario they cover (e.g. `capex_spike_benign`, `capex_spike_concerning`, `transcript_unavailable_gap`), not for the mechanism being tested.
- **Golden files**: `tests/golden/<ticker>_<fixture_type>.{json,html}`, sourced from real captured API/filing responses (trimmed for size where needed, verified the trim doesn't change parsed output), never hand-constructed.

---

## Commands

All verified working, including live runs against real APIs (Phase 0) and a real Anthropic model (Phase 1, Phase 2).

- **Unit + plumbing tests** (network-free, key-free — the CI-safe suite, includes `TestModel`-based agent tests): `uv run pytest tests/unit -q`
- **Lint**: `uv run ruff check .`
- **Type-check**: `uv run pyright src tests evals`
- **Clear the disk cache** (force fresh fetches): `uv run python -c "from agentic_fundamental_analyst.data.cache import clear_cache; clear_cache()"`
- **Fetch one ticker live** (requires real `FRED_KEY`/`TIINGO_KEY` in `.env`; returns a 5-tuple as of Phase 2):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  asyncio.run(fetch_all("GOOGL"))  # -> (financials, filings, macro, prices, transcript | None)
  ```
- **Run all four Stage-2/3 agents on one ticker end to end** (requires real `FRED_KEY`/`TIINGO_KEY`/`ANTHROPIC_API_KEY` in `.env`; live-verified against GOOGL and MBUU):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  from agentic_fundamental_analyst.agents.financial_statements import run_financial_statements_analyst
  from agentic_fundamental_analyst.agents.filings import run_filings_analyst
  from agentic_fundamental_analyst.agents.transcript import run_transcript_analyst
  from agentic_fundamental_analyst.agents.flag_consolidator import run_flag_consolidator

  async def main():
      financials, filings, macro, prices, transcript = await fetch_all("GOOGL")
      fin_out = await run_financial_statements_analyst(financials)
      filings_out = await run_filings_analyst("GOOGL", filings)
      transcript_out = await run_transcript_analyst("GOOGL", transcript)
      consolidated = await run_flag_consolidator(fin_out.flags + filings_out.flags + transcript_out.flags)
      print(filings_out.model_dump_json(indent=2))

  asyncio.run(main())
  ```
- **Run an eval dataset** (requires real `ANTHROPIC_API_KEY`; live-verified scores in Current State): `uv run python -m evals.financial_statements` / `evals.filings` / `evals.transcripts` / `evals.flag_consolidator`
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
- **Contracts**: `src/agentic_fundamental_analyst/contracts/` — `financials.py`, `filings.py`, `macro.py`, `prices.py`, `intake.py`, `ratios.py`, `valuation.py`, `sourcing.py` (`SourcedFigure`/`SourcedQuote`), `flags.py` (`Flag`/`Severity`), `financial_analyst.py`, `transcripts.py`, `filings_analyst.py`, `transcript_analyst.py`, `consolidation.py`.
- **EDGAR client**: `src/agentic_fundamental_analyst/data/edgar.py` — see `.agents/references/data-layer.md` for the four non-obvious XBRL merge bugs (Phase 0/1) plus Phase 2's 8-K lookback-scan and transcript-exhibit-discovery extensions.
- **Filing HTML parsing**: `src/agentic_fundamental_analyst/data/filing_sections.py` — bold/non-hyperlinked "Item N." heuristic (now incl. Item 9A), plus `looks_like_transcript_body()`/`extract_plain_text()` (Phase 2).
- **Ratio/valuation math**: `src/agentic_fundamental_analyst/ratios.py` (incl. `compute_trend_bundle` — annual-only, see Current State gap note), `valuation.py`.
- **Cross-analyst flag dedup**: `src/agentic_fundamental_analyst/flags.py` (`deduplicate_exact_flags`) — Phase 2.
- **Agents**: `agents/financial_statements.py` (Phase 1), `agents/filings.py`/`agents/transcript.py`/`agents/flag_consolidator.py` (Phase 2), `agents/grounding.py` (shared verbatim-quote check). See `.agents/plans/phase-1-financial-statements-analyst.md` and `.agents/plans/phase-2-filings-transcript-consolidator.md` for why each agent's output type is shaped the way it is.
- **Logfire bring-up**: `src/agentic_fundamental_analyst/observability.py`.
- **Eval datasets**: `evals/financial_statements.py`, `evals/filings.py`, `evals/transcripts.py`, `evals/flag_consolidator.py`, `evals/grounding.py` (shared check).
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

`data-layer.md`, `free-data-sources.md`, `valuation.md` (Phase 0), `agents.md`, `observability.md` (Phase 1), and `evals.md` (Phase 2) are now filled in.
