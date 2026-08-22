# Observability — Implementation Reference

For the observability strategy's design intent, see `PRD.md` §9. This file covers what's actually
built and confirmed, updated as each phase touches it.

## Logfire bring-up (Phase 1)

**Module**: `src/agentic_fundamental_analyst/observability.py`. Called at import time, mirroring
`config.py`'s "load once, regardless of import order" pattern:

```python
logfire.configure(send_to_logfire="if-token-present")
logfire.instrument_pydantic_ai()
```

`send_to_logfire="if-token-present"` is confirmed (against `logfire/_internal/config.py`, version
4.40.0) as a real accepted value: `bool | Literal['if-token-present'] | None`. It sends data only
when a token is available (via `LOGFIRE_TOKEN` env var or local `logfire auth` credentials under
`~/.logfire`); otherwise it configures a local no-op tracer — **no network call, no hang, no
interactive prompt**. This was verified directly: importing `observability` with `LOGFIRE_TOKEN`
unset completes instantly.

**Why this matters for testing**: every agent module (`agents/financial_statements.py` and every
one after it) imports `observability` at module level for its side effect. `tests/unit` imports
agent modules to override them with `TestModel` — so `observability`'s import-time behavior had to
be proven safe key-free/network-free before any plumbing test could be trusted. It is.

**Setup for a human running this locally** (not scriptable — interactive login):
```bash
uv run logfire auth
uv run logfire projects new   # or: uv run logfire projects use
```
This writes credentials to `~/.logfire`; no `LOGFIRE_TOKEN` needs to live in `.env` for local runs
after that (though `.env.example` documents the var for environments without CLI auth, e.g. CI).

## Per-agent instrumentation

`Agent(..., name="financial_statements_analyst")` — every agent gets `name=` so its run span is
identifiable (per CLAUDE.md convention), auto-captured by `logfire.instrument_pydantic_ai()`:
token usage, `operation.cost`, one span per model request.

## Per-stage spans (Phase 1 pattern — repeat for every future stage)

`run_financial_statements_analyst()` wraps its work in:
```python
with logfire.span("financial_statements_analyst_stage", ticker=bundle.ticker) as span:
    ...
    span.set_attribute("flag_count", len(flags))
    span.set_attribute("dropped_candidate_count", len(dropped))
```
`dropped_candidate_count` is Phase 1-specific signal worth watching: a nonzero, persistent count
across real runs would mean the model is regularly naming metrics/periods it can't see, which is
exactly the failure mode the grounding design exists to catch — check the trace, not just the eval
score, if this shows up.

**Not yet done**: trace-wide `ticker` baggage attribute (PRD §9 — "every span in the trace,
filterable by ticker") is a pipeline-level concern; `pipeline.py` doesn't exist until Phase 5. This
phase's span carries `ticker` locally as a stopgap, not as trace-wide baggage.

**Status of live verification**: confirmed against real tickers (GOOGL, MBUU) for all four agents
built so far (Phase 1 + Phase 2). Span structure, live-verified:
`financial_statements_analyst_stage` → `financial_statements_analyst` run → `chat claude-sonnet-5`;
`filings_analyst_stage` → `filings_analyst` run → `chat claude-sonnet-5`;
`flag_consolidator_stage` → `flag_consolidator` run → `chat claude-haiku-4-5-20251001` — all with
`gen_ai.usage.*`/`operation.cost` populated and `flag_count`/`dropped_candidate_count` (or
`consolidated_group_count`/`dropped_group_reference_count` for the Consolidator) on the outer span.

## Phase 2: the Transcript Analyst's *absent* span

`transcript_analyst_stage` only appears in a trace when a transcript was actually found —
confirmed live against both GOOGL and MBUU (neither has one in recent 8-K history; no span, no
model call, appeared for either run). This is the Transcript Analyst's structural
no-fabrication guarantee made visible in the trace: the `None` short-circuit in
`run_transcript_analyst()` returns before `logfire.span(...)` is ever entered, not just before the
model is called. If a `transcript_analyst_stage` span is ever *missing* from a trace where a real
transcript should exist, that's a real bug to chase (the lookback scan or exhibit-discovery logic
failing silently) — but its absence on a ticker with no transcript is expected, not an error.

## Phase 3: the Investigator's span

`investigator_stage` (in `agents/investigator.py::run_investigator()`) carries `metric`/`severity` on
open, and on close: `verdict`, `confidence`, `search_count`, `raw_result_domain_count` (every domain
any raw `web_search` call returned, including irrelevant noise), `evidence_domain_count` (domains of
the model's actually-*cited*, grounded evidence — the metric that drives the multi-angle enforcement;
deliberately distinct from `raw_result_domain_count`, see `agents.md`), and
`dropped_evidence_count`. Nests `investigator run` → `chat claude-opus-5`, same shape as the other
four agents. On a budget overrun (`UsageLimitExceeded`), the span still closes cleanly with
`verdict="unresolved"` and `budget_exceeded=True` — the degrade-gracefully path never lets the span
(or the run) fail open.

Native `web_search`/`web_fetch` calls do **not** appear as their own child spans (they're
provider-executed, represented as message parts, not OTel spans — see `evals.md`'s Trajectory evals
section) — don't go looking for a `web_search` tool-call span in the trace; it isn't there. The
signal for "did it actually search broadly" lives on the `investigator_stage` span's own attributes
above, derived from the typed `InvestigationTrajectory`/evidence, not from child spans.

Live-verified (GOOGL, 2026-08-19): `investigator_stage` → `investigator run` → `chat claude-opus-5`,
nested correctly alongside `financial_statements_analyst_stage`, `filings_analyst_stage`, and
`flag_consolidator_stage` in one run (no `transcript_analyst_stage`, correctly — GOOGL has no
transcript this run either). On the real consolidated capex flag: `search_count=6`,
`dropped_evidence_count=0`, 11 grounded evidence items cited (vs. 35 raw noise domains returned by
search) — exactly the gap `evidence_domain_count` exists to see past.

## Phase 5: the three Synthesis stages' spans, and `pipeline.py`'s own wiring

`synthesizer_draft_stage`, `red_team_stage`, `synthesizer_resolve_stage` (in
`agents/synthesizer_draft.py`/`agents/red_team.py`/`agents/synthesizer_resolve.py`) follow the
same per-stage span pattern as every prior agent. Attributes worth watching:
`section_fallback_count` / `section_missing_count` (draft and resolve — nonzero is the
`fallback_triggered` grounding signal made visible in the trace, same "check the trace, not just
the eval score" precedent as Phase 1's `dropped_candidate_count`), `attack_count` /
`dropped_candidate_count` (red-team), and `unaddressed_attack_count` (resolve — should be 0 on a
healthy run; nonzero means `_fill_missing_resolutions`'s structural fallback fired, i.e. the
model left at least one attack without a real resolution).

`pipeline.py::run_memo_pipeline()` does **not** yet wrap the whole run in a single outer span
with trace-wide `ticker` baggage — PRD §9's "one trace per pipeline run... every span filterable
by ticker" is still open. The plan flagged this explicitly as something to verify against real
Logfire/pydantic-ai API before writing (not guess), and the Level 4 live run needed to actually
confirm the trace shape never completed (see below) — so every stage still only carries `ticker`
as a local span attribute, same stopgap noted since Phase 1. Revisit once a live pipeline run
succeeds.

**Not live-verified**: a real `run_memo_pipeline("GOOGL")` run — attempted three times, each
failing identically with a 429 (`This request would exceed your rate limit of 500,000 input
tokens per minute`) on `synthesizer_draft`'s own request, before any Phase 5 span could even be
recorded. Not a code defect — every other validation level (unit tests, all three Phase 5 eval
datasets, lint/type-check) completed successfully against real API calls in the same session;
this is specifically the single largest possible payload (a real ticker's full
`MemoSynthesisInput`) hitting an account-level rate-limit wall. Full account:
`.agents/plans/phase-5-synthesis-redteam-pipeline.md` Execution Deviations §5.

## Dashboards, annotation workflow

Not yet built. `pipeline.py` (Phase 5) now exists and `render.py` can turn its output into a real
PDF, but the Level 4 live GOOGL run that would generate the first real end-to-end trace hasn't
completed (see above) — dashboards remain deferred until that succeeds. Three real bugs this
phase (two implementation, one eval fixture — see `evals.md`) were still caught by inspecting
eval-run output directly, the same annotation-flywheel precedent as Phase 2's two fixture fixes,
just not yet from a production trace.
