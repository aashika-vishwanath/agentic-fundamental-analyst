# Initialize Project

Set up a working local environment for the analyst pipeline. This is a Python pipeline project — no server, no database container. Setup = dependencies + API credentials + cache + observability + a validation ladder that proves each layer works before spending any API tokens.

## 1. Create Environment File

```bash
cp .env.example .env
```

Then fill in the required values. `.env.example` documents each; typical set:

| Variable | Purpose | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | LLM providers (per model-tier assignments) | Yes for live runs; not for offline tests |
| `SEC_EDGAR_USER_AGENT` | EDGAR requires an identifying UA string (`name email`) | Yes |
| `<FINANCIAL_DATA_API_KEY>` | Financials/estimates/transcripts provider | Yes for fetch; cached data works without |
| `FRED_API_KEY` | Macro series | Yes for macro refresh |
| `LOGFIRE_TOKEN` | Observability (or use `logfire auth` below) | Recommended |

**Never commit `.env`.** Keys load via environment only (CLAUDE.md hard constraint).

## 2. Install Dependencies

```bash
uv sync
```

Installs everything in `pyproject.toml`, including dev/eval groups.

## 3. Authenticate Logfire

```bash
uv run logfire auth        # one-time browser auth, or set LOGFIRE_TOKEN in .env
uv run logfire projects use <project-name>
```

Observability is wired from the first run — don't skip this.

## 4. Initialize the Data Cache

```bash
mkdir -p <cache-dir>       # per CLAUDE.md conventions
uv run <fetch-command> --ticker <TEST_TICKER>
```

Pulls and caches one ticker's filings/financials/transcript so everything downstream can run **offline** — faster iteration, zero repeat API cost, and the basis for golden files.

## 5. Validate Setup — the ladder

Run in order; each level proves a layer without depending on the next.

```bash
# Level 1 — no network, no keys: golden-file + contract tests
uv run pytest tests/unit -q

# Level 2 — no LLM spend: TestModel plumbing tests (agents wire up, outputs validate)
uv run pytest tests/plumbing -q

# Level 3 — data layer live: fetch + parse the test ticker end to end
uv run <data-layer-smoke-command> --ticker <TEST_TICKER>

# Level 4 — one real LLM call: single agent against cached data
uv run <single-agent-command> --ticker <TEST_TICKER>
# → then open Logfire and confirm the trace appears with cost attributes
```

Levels 1–2 must pass with **no API keys at all** — that's the CI contract. Levels 3–4 confirm credentials and observability.

## Access Points

- Logfire dashboard: `https://logfire.pydantic.dev/<org>/<project>`
- Cached data: `<cache-dir>/`
- Eval reports: surface in Logfire as experiments after any eval run

## Common Issues

- **EDGAR 403** → `SEC_EDGAR_USER_AGENT` missing or not `name email` format
- **Provider 429** → free-tier rate limit; rely on cache, add backoff in the data layer, don't loop retries by hand
- **No trace in Logfire** → auth step skipped, or `logfire.configure()` not reached before the run

## Cleanup

Nothing to stop — no long-running services. To reset:

```bash
rm -rf <cache-dir>/        # clear cached data (refetch on next run)
```