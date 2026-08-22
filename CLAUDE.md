# CLAUDE.md

## Project Overview

Given a US-listed, SEC-filing, non-financial operating company ticker, this system produces a grounded investment memo with a Buy/Hold/Sell recommendation. Architecture: a fixed deterministic pipeline (plain async Python) with agentic islands — single-shot document-grounded agents for interpretation, and exactly one real agentic loop (the Investigator, with web search) for anomaly investigation. Full detail, rationale, and the complete agent/data/phase spec: **`PRD.md`** — this file is constraints and pointers only, never a substitute for it.

Status: Phases 0-5 complete and tested, incl. a real GOOGL end-to-end `run_memo_pipeline()` run (2026-08-22; see Current State). `pyproject.toml` exists (uv-managed); `src/agentic_fundamental_analyst/` has the full deterministic data layer, ten single-shot analyst agents, the Investigator (the system's one agentic loop), and `pipeline.py`'s full end-to-end orchestration plus Markdown/PDF rendering. The Conventions section below reflects code that exists, not just a plan.

---

## Current State

**Completed**: Phase 0 (deterministic data layer), Phase 1 (Financial Statements Analyst), Phase 2 (Filings Analyst, Transcript Analyst, Flag Consolidator), Phase 3 (Investigator), Phase 4 (Sector Analyst, Macro Sensitivity Analyst, Valuation Interpreter), Phase 5 (Synthesizer draft + resolve, Red-Team, `pipeline.py`, Markdown/PDF rendering). Built, tested, and live-verified end-to-end against a real ticker (GOOGL, 2026-08-22) — see below.
- Data layer: `EdgarClient`, `FredClient`, `PriceClient`, cache, `ratios.py` (now incl. `build_company_macro_profile()`, Phase 5), `valuation.py`, `fetch_all()` (returns a 6-tuple, leading with `TickerIntakeResult`). Phase 4 added SIC-based peer discovery and trailing-FCF/discount-rate wiring. Detail in `.agents/references/data-layer.md`.
- Agents: `financial_statements.py` (Phase 1), `filings.py`/`transcript.py`/`flag_consolidator.py` (Phase 2), `investigator.py` (Phase 3), `sector.py`/`macro.py`/`valuation_interpreter.py` (Phase 4), `synthesizer_draft.py`/`red_team.py`/`synthesizer_resolve.py` (Phase 5) — all Sonnet-tier (PRD §10; Phase 5's tier was revised this session from an original Opus starting point given token cost, and is explicitly a starting point pending eval-justified revision, not a final decision). **Five** grounding mechanisms: numeric closed-table lookup (Phase 1), verbatim quoted-evidence substring checking (`agents/grounding.py`, Filings/Transcript/Red-Team), URL provenance (`agents/provenance.py`, Investigator), numeric-value tolerance matching (`agents/numeric_grounding.py`, Phase 4), and per-section numeric-value tolerance matching over a much larger known-numbers universe (`agents/memo_grounding.py`, Phase 5 — extends Phase 4's module rather than reimplementing, with its own bounded pairwise-expansion since the shared unbounded version broke down at Phase 5's scale). `Flag.source` is `SourcedFigure | SourcedQuote`. Full rationale: per-phase plan files in `.agents/plans/`.
- **Investigator** (`agents/investigator.py`, `anthropic:claude-opus-5`): the one agentic loop, `WebSearch`/`WebFetch`/`Thinking`. Deterministically enforces "no one-to-one flag-to-source mapping" via ≥2 distinct cited-evidence domains. Cost governed three ways (`max_uses`, `UsageLimits(cost_limit=$0.75)`, `max_investigations=5`); a budget overrun degrades to `unresolved` + `CoverageGap`.
- **Phase 4** (`agents/sector.py`/`agents/macro.py`/`agents/valuation_interpreter.py`): pure narration, no tools, no Flags, verified by a runtime numeric-grounding gate. Peer discovery runs once and feeds both Sector Analyst and Valuation Interpreter.
- **Phase 5** (`agents/synthesizer_draft.py`/`agents/red_team.py`/`agents/synthesizer_resolve.py`, `pipeline.py`, `render.py`): draft pass writes all 10 of PRD §3's memo sections (fixed order via the closed `MemoSectionTitle` Literal, `contracts/memo.py::MEMO_SECTION_ORDER`) from a `MemoSynthesisInput` bundling every upstream typed output; red-team attacks for `untraceable_claim`/`boilerplate` (verbatim-quote-grounded, independently re-checks the earnings-quality checklist); resolve pass answers or downgrades every attack with a structural, code-enforced completeness guarantee (every attack index gets exactly one `AttackResolution`, PRD §14's named sycophancy risk targeted directly, not just prompted against) and rewrites all 10 sections. `pipeline.py::run_memo_pipeline(ticker)` wires phases 0-5 into one call; `render.py` turns the resulting `Memo` into Markdown/PDF (pure formatting, deliberately never called from the pipeline itself). All three new agents needed an explicit `model_settings=ModelSettings(max_tokens=…)` — pydantic-ai's 4096 default silently truncated a full memo's output before shipping; a real, previously-deferred gap (`CompanyMacroProfile` construction) got closed via `ratios.py::build_company_macro_profile()`. Full account, incl. two more real bugs caught only by running the new eval datasets live (not by any unit test): `.agents/plans/phase-5-synthesis-redteam-pipeline.md` Execution Deviations. Three more real bugs surfaced only by the first successful real-ticker `run_memo_pipeline()` run (2026-08-22, none caught by any eval dataset's small synthetic fixtures): (1) the actual rate-limit cause was never filing text — `data/fetch.py`'s FRED calls pulled full series history since inception (DGS10 back to 1962), making `macro_bundles` alone ~7x bigger than the filing text everyone assumed was the driver; fixed with a 5-year window (`_MACRO_LOOKBACK`); (2) Anthropic's model occasionally serialized the large `sections` array as an escaped JSON string instead of a native array under real-scale generation load — fixed with a `model_validator(mode="before")` coercion (`contracts/memo.py::_coerce_stringified_list_fields`) on all three Phase 5 output types; (3) `max_tokens=8192` (already once-raised) was still insufficient for a real company's full memo — raised to 32000/20000/32000 across draft/red-team/resolve (Sonnet 5 supports up to 128K output; billed on tokens actually used, so generous headroom is free).
- Logfire wired up and confirmed producing real traces for all eleven agents, incl. the Transcript Analyst's no-span-when-absent behavior, the Investigator's trajectory attributes, Phase 4's peer-discovery/grounding attributes, and Phase 5's `section_fallback_count`/`unaddressed_attack_count` stage attributes. `pipeline.py` does not yet wrap a run in one outer trace-wide-`ticker`-baggage span (PRD §9) — still open, same stopgap as every prior phase.
**Known permanent gaps**: Stooq blocked (Tiingo-only pricing); `cash_conversion_cycle()` can't compute; 10-Q periods excluded from ratio-trend math; Filings Analyst checklist items #9/#14 only partially covered; DEF 14A/Forms 3/4/5 out of scope; SIC-code-based peer sets can be low quality for broad SIC codes; no filing-text truncation strategy anywhere in the pipeline (a real `MemoSynthesisInput` for a large filer can be large enough to hit per-minute API rate limits — see below). Detail in `data-layer.md` and the per-phase plans.
**Cost note**: Investigator remains the per-call cost leader, **$0.36-$1.14/flag**. Filings Analyst ~$0.13-0.28/call. Phase 4's three agents are cents/run each. Phase 5's three agents are the largest single prompts in the pipeline (a full `MemoSynthesisInput`, three times in sequence) — real observed eval-run cost ~$0.02-0.20/call depending on stage, but a real ticker's full filing text pushes this much higher; the PRD's ~$2/run ceiling has not yet been validated end-to-end (see below).
**Tests**: 186 unit tests passing (network-free, key-free; up from 157 at the Phase 4 baseline). Eval datasets, all live-verified against the real model: Phases 1-4's eight datasets unchanged and passing (see prior entries in this file's history / `evals.md`); Phase 5's three new datasets — `evals/synthesizer_draft.py` (3 cases: all deterministic/recall evaluators 100%, LLMJudge 3/3, grounding-fallback signal fired once — investigated, confirmed to be the safety net correctly self-healing a one-off ungrounded claim, not a defect), `evals/red_team.py` (4 cases: all evaluators 100%, incl. a real fixture bug found and fixed — see `evals.md`), `evals/synthesizer_resolve.py` (4 cases: all hard/structural gates 100%, `ExpectedResolutionPath` 4/4, LLMJudge 4/4, grounding-fallback signal fired on 2/4 cases, same self-healing pattern). Full account: `evals.md`.
**Not yet live-verified**: a real `run_memo_pipeline("GOOGL")` end-to-end run. Attempted three times across ~10 minutes; each attempt 429'd identically on `synthesizer_draft`'s own request (`This request would exceed your rate limit of 500,000 input tokens per minute`) — a real ticker's full filing text plus the rest of `MemoSynthesisInput` plausibly approaches a meaningful fraction of this account's per-minute cap on its own. Not a code defect (every other validation level passed against real API calls); candidate fixes (confirm/raise the account's rate-limit tier, or design a filing-text truncation strategy) are Phase 6-shaped. `run_memo_pipeline()` and `render_memo_to_pdf()` are both implemented and plumbing-tested (`TestModel`-scripted full call graph, `tests/unit/test_pipeline.py`) — re-run this once resolved.
**Next up**: Phase 6 — hardening: resolve the Phase 5 rate-limit blocker (confirm account tier or design filing-text truncation), spend-limit decisions, fallback models, cost/latency/eval dashboards, the trace-wide `ticker` baggage attribute, and the standing full-regression-suite gate.

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

**Layout** (Phase 0-5 all built):
```
src/agentic_fundamental_analyst/
  config.py       # loads .env once at import time (FRED_KEY, TIINGO_KEY, EDGAR_USER_AGENT, ANTHROPIC_API_KEY, LOGFIRE_TOKEN)
  observability.py # Logfire bring-up (logfire.configure + instrument_pydantic_ai), import-time, token-optional
  data/           # EdgarClient, FredClient, PriceClient, cache layer, filing_sections.py, sic_lookup.py,
                  # peer_discovery.py (Phase 4), fetch_all()
  contracts/      # Pydantic models — financials, filings, macro, prices, intake, ratios, valuation, sourcing, flags,
                  # financial_analyst, transcripts, filings_analyst, transcript_analyst, consolidation,
                  # sector_analyst, macro_analyst, valuation_interpreter (Phase 4), memo, synthesis (Phase 5)
  agents/         # models.py (model-tier constants) + grounding.py (shared quote-grounding) +
                  # numeric_grounding.py (Phase 4, shared numeric-value grounding) +
                  # memo_grounding.py (Phase 5, per-section numeric grounding) + one module per agent role
    financial_statements.py  # Phase 1: financial_statements_analyst, run_financial_statements_analyst()
    filings.py                # Phase 2: filings_analyst, run_filings_analyst(ticker, sections)
    transcript.py               # Phase 2: transcript_analyst, run_transcript_analyst(ticker, transcript | None)
    flag_consolidator.py         # Phase 2: flag_consolidator, run_flag_consolidator(all_flags)
    sector.py                     # Phase 4: sector_analyst, run_sector_analyst(peer_data)
    macro.py                       # Phase 4: macro_sensitivity_analyst, run_macro_sensitivity_analyst(macro, profile)
    valuation_interpreter.py        # Phase 4: valuation_interpreter, run_valuation_interpreter(result)
    synthesizer_draft.py             # Phase 5: synthesizer_draft, run_synthesizer_draft(input) -> MemoDraft
    red_team.py                       # Phase 5: red_team, run_red_team(input) -> RedTeamAttack
    synthesizer_resolve.py             # Phase 5: synthesizer_resolve, run_synthesizer_resolve(input) -> Memo
  flags.py        # deterministic exact-dedup (deduplicate_exact_flags) — Phase 2, sibling to ratios.py/valuation.py
  ratios.py       # deterministic ratio math (DSO, Sloan accruals, cash conversion, Beneish x8, trend, build_company_macro_profile)
  valuation.py    # deterministic DCF/comps math, trailing_free_cash_flows/build_valuation_assumptions (Phase 4)
  pipeline.py     # Phase 5: run_memo_pipeline(ticker), the orchestrator
  render.py       # Phase 5: render_memo_to_markdown/render_memo_to_pdf — deterministic, never called from pipeline.py
evals/            # Pydantic Evals Datasets, one file per agent, plus grounding.py (shared quote-grounding check)
tests/
  conftest.py     # sets a placeholder ANTHROPIC_API_KEY + ALLOW_MODEL_REQUESTS=False before collection (see Current State gotcha)
  unit/           # network-free unit tests (respx-mocked + TestModel), 186 passing
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
- **Fetch one ticker live** (requires real `FRED_KEY`/`TIINGO_KEY` in `.env`; returns a **6-tuple as of Phase 4**):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  asyncio.run(fetch_all("GOOGL"))  # -> (intake, financials, filings, macro, prices, transcript | None)
  ```
- **Run all Stage-2/3/4 agents on one ticker end to end, incl. the Investigator** (requires real `FRED_KEY`/`TIINGO_KEY`/`ANTHROPIC_API_KEY` in `.env`; live-verified against GOOGL and MBUU (Stage 2/3) and GOOGL (incl. Investigator, 2026-08-19) — **spends real money**, the Investigator alone runs ~$0.36-$1.14 per consolidated flag):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  from agentic_fundamental_analyst.agents.financial_statements import run_financial_statements_analyst
  from agentic_fundamental_analyst.agents.filings import run_filings_analyst
  from agentic_fundamental_analyst.agents.transcript import run_transcript_analyst
  from agentic_fundamental_analyst.agents.flag_consolidator import run_flag_consolidator
  from agentic_fundamental_analyst.agents.investigator import run_investigations

  async def main():
      intake, financials, filings, macro, prices, transcript = await fetch_all("GOOGL")
      fin_out = await run_financial_statements_analyst(financials)
      filings_out = await run_filings_analyst("GOOGL", filings)
      transcript_out = await run_transcript_analyst("GOOGL", transcript)
      consolidated = await run_flag_consolidator(fin_out.flags + filings_out.flags + transcript_out.flags)
      verdicts, stage_gaps = await run_investigations(consolidated)  # max_investigations=5 default
      print([v.verdict.value for v in verdicts])

  asyncio.run(main())
  ```
- **Run the Phase 4 agents on one ticker end to end** (requires real `FRED_KEY`/`TIINGO_KEY`/`ANTHROPIC_API_KEY` in `.env`; live-verified against GOOGL, 2026-08-19 — cheap, low cents/run, but peer discovery adds real EDGAR-call-count latency):
  ```python
  import asyncio
  from agentic_fundamental_analyst.data.fetch import fetch_all
  from agentic_fundamental_analyst.data.peer_discovery import discover_sector_peers
  from agentic_fundamental_analyst.agents.sector import run_sector_analyst
  from agentic_fundamental_analyst.agents.macro import run_macro_sensitivity_analyst
  from agentic_fundamental_analyst.agents.valuation_interpreter import run_valuation_interpreter
  from agentic_fundamental_analyst.contracts.valuation import ValuationResult
  from agentic_fundamental_analyst.valuation import build_valuation_assumptions, dcf, trailing_free_cash_flows
  from agentic_fundamental_analyst.ratios import build_company_macro_profile

  async def main():
      intake, financials, filings, macro, prices, transcript = await fetch_all("GOOGL")
      latest_price = max(prices.bars, key=lambda b: b.bar_date).close
      peer_data = await discover_sector_peers(
          "GOOGL", intake.cik, intake.sic_code, intake.sic_description, latest_price
      )
      sector_out = await run_sector_analyst(peer_data)
      profile = build_company_macro_profile("GOOGL", intake.sic_description, financials)  # Phase 5 — closes the prior None-placeholder gap
      macro_out = await run_macro_sensitivity_analyst(macro, profile)
      assumptions = build_valuation_assumptions(macro)
      flows = trailing_free_cash_flows(financials)
      dcf_result = dcf(flows, assumptions.discount_rate, assumptions.terminal_growth) if flows and assumptions else None
      valuation_out = await run_valuation_interpreter(
          ValuationResult(ticker="GOOGL", assumptions=assumptions, dcf=dcf_result,
                          comps=peer_data.comps, coverage_gaps=peer_data.coverage_gaps)
      )
      print(sector_out.summary, macro_out.summary, valuation_out.summary)

  asyncio.run(main())
  ```
- **Run an eval dataset** (requires real `ANTHROPIC_API_KEY`; live-verified scores in Current State — `evals.investigator` spends real money, ~$1.50-2.50/full run, and makes real web searches; the Phase 4 datasets are cheap, low cents/run; Phase 5's three datasets are also cheap, ~$0.02-0.20/call): `uv run python -m evals.financial_statements` / `evals.filings` / `evals.transcripts` / `evals.flag_consolidator` / `evals.investigator` / `evals.sector_analyst` / `evals.macro_analyst` / `evals.valuation_interpreter` / `evals.synthesizer_draft` / `evals.red_team` / `evals.synthesizer_resolve`
- **Logfire auth** (one-time, interactive — run yourself, not scriptable): `uv run logfire auth`, then `uv run logfire projects new` (or `use`)
- **Run the full pipeline for one ticker and render a PDF** (requires real `FRED_KEY`/`TIINGO_KEY`/`ANTHROPIC_API_KEY` in `.env` — **spends real money across all eleven agents**, and a large filer's real filing text can be big enough to hit Anthropic's per-minute input-token rate limit on the `synthesizer_draft` call; not yet live-verified against a real ticker end-to-end for this reason — see Current State):
  ```python
  import asyncio
  from agentic_fundamental_analyst.pipeline import run_memo_pipeline
  from agentic_fundamental_analyst.render import render_memo_to_pdf

  async def main():
      memo = await run_memo_pipeline("GOOGL")
      print(memo.rating, memo.conviction, len(memo.sections), len(memo.coverage_gaps))
      render_memo_to_pdf(memo, "googl_memo.pdf")

  asyncio.run(main())
  ```

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

- **Data fetch entry point**: `src/agentic_fundamental_analyst/data/fetch.py` (`fetch_all(ticker)`) — gated on `TickerIntakeResult.in_scope`, raises `TickerOutOfScope` for excluded sectors before any other fetch. Returns a 6-tuple as of Phase 4.
- **Contracts**: `src/agentic_fundamental_analyst/contracts/` — `financials.py`, `filings.py`, `macro.py`, `prices.py`, `intake.py`, `ratios.py`, `valuation.py` (incl. `ValuationAssumptions`/`ValuationResult`, Phase 4), `sourcing.py` (`SourcedFigure`/`SourcedQuote`), `flags.py` (`Flag`/`Severity`), `financial_analyst.py`, `transcripts.py`, `filings_analyst.py`, `transcript_analyst.py`, `consolidation.py`, `investigation.py` (`InvestigationVerdict`/`VerdictType`/`EvidenceItem`/`InvestigationTrajectory`), `sector_analyst.py`/`macro_analyst.py`/`valuation_interpreter.py` (Phase 4), `memo.py` (`Memo`/`MemoDraft`/`MemoSection`/`RedTeamAttack`/`AttackResolution`/`MEMO_SECTION_ORDER`, Phase 5), `synthesis.py` (`MemoSynthesisInput`/`RedTeamInput`/`SynthesizerResolveInput`, Phase 5).
- **EDGAR client**: `src/agentic_fundamental_analyst/data/edgar.py` — see `.agents/references/data-layer.md` for the four non-obvious XBRL merge bugs (Phase 0/1), Phase 2's 8-K lookback-scan and transcript-exhibit-discovery extensions, and Phase 4's SIC-based peer discovery (incl. the browse-edgar feed's broken name/title fields and the feed-page-size-vs-candidate-cap bug caught live).
- **Filing HTML parsing**: `src/agentic_fundamental_analyst/data/filing_sections.py` — bold/non-hyperlinked "Item N." heuristic (now incl. Item 9A), plus `looks_like_transcript_body()`/`extract_plain_text()` (Phase 2).
- **Ratio/valuation math**: `src/agentic_fundamental_analyst/ratios.py` (incl. `compute_trend_bundle` — annual-only, see Current State gap note; `build_company_macro_profile`, Phase 5), `valuation.py` (incl. `trailing_free_cash_flows`/`build_valuation_assumptions`, Phase 4).
- **Cross-analyst flag dedup**: `src/agentic_fundamental_analyst/flags.py` (`deduplicate_exact_flags`) — Phase 2.
- **Peer discovery**: `src/agentic_fundamental_analyst/data/sic_lookup.py` (pure XML parsing), `src/agentic_fundamental_analyst/data/peer_discovery.py` (`discover_sector_peers()` orchestration) — Phase 4.
- **Agents**: `agents/financial_statements.py` (Phase 1), `agents/filings.py`/`agents/transcript.py`/`agents/flag_consolidator.py` (Phase 2), `agents/investigator.py` (Phase 3, the one agentic loop), `agents/sector.py`/`agents/macro.py`/`agents/valuation_interpreter.py` (Phase 4), `agents/synthesizer_draft.py`/`agents/red_team.py`/`agents/synthesizer_resolve.py` (Phase 5), `agents/grounding.py` (shared verbatim-quote check — Filings/Transcript/Red-Team), `agents/provenance.py` (URL-provenance grounding + trajectory extraction — Investigator's own mechanism), `agents/numeric_grounding.py` (shared numeric-value grounding — the three Phase 4 agents' mechanism), `agents/memo_grounding.py` (per-section numeric grounding over a larger known-numbers universe — the three Phase 5 synthesis agents' mechanism). See the per-phase plan files in `.agents/plans/` for why each agent's output type is shaped the way it is.
- **Logfire bring-up**: `src/agentic_fundamental_analyst/observability.py`.
- **Eval datasets**: `evals/financial_statements.py`, `evals/filings.py`, `evals/transcripts.py`, `evals/flag_consolidator.py`, `evals/investigator.py`, `evals/sector_analyst.py`, `evals/macro_analyst.py`, `evals/valuation_interpreter.py`, `evals/synthesizer_draft.py`, `evals/red_team.py`, `evals/synthesizer_resolve.py`, `evals/grounding.py` (shared quote check).
- **Pipeline entry point**: `src/agentic_fundamental_analyst/pipeline.py` (`run_memo_pipeline(ticker)`) — Phase 5, wires phases 0-5 into one call.
- **Rendering**: `src/agentic_fundamental_analyst/render.py` (`render_memo_to_markdown`/`render_memo_to_pdf`) — Phase 5, deterministic, never called from `pipeline.py`.

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
