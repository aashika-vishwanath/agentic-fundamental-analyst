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

**Status of live verification**: configuration is proven safe to import; a real trace has **not**
yet been produced or inspected in this environment (blocked on `ANTHROPIC_API_KEY` — see CLAUDE.md
Current State). Do this before considering Phase 1 fully closed: run the Financial Statements
Analyst against a real ticker (Commands section has the exact snippet) and confirm in the Logfire
UI: a `financial_statements_analyst_stage` span tagged `ticker`, a nested
`financial_statements_analyst` agent-run span with `gen_ai.usage.*` and `operation.cost`
populated, and `flag_count`/`dropped_candidate_count` on the outer span.

## Dashboards, annotation workflow

Not yet built — no real traces exist yet to build a dashboard against. Revisit once Level 4 above
is done and a handful of real runs exist.
