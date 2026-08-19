"""Stooq CSV bulk-backfill fallback — currently BLOCKED, not implemented.

As of Phase 0 execution (2026-08), stooq.com's CSV download endpoint
(`stooq.com/q/d/l/?s=TICKER&i=d`) returns a JavaScript proof-of-work
challenge page instead of CSV data for any plain HTTP client (confirmed via
curl with a real browser User-Agent, and via a fetch tool with markdown
conversion) — a bot-detection change since free-data-sources.md's original
research, which found it worked keylessly over plain HTTP. Solving the
challenge requires executing arbitrary JavaScript (SHA-256 proof-of-work +
a follow-up POST), which is out of scope for this deterministic, headless
data layer.

Stooq is the backfill fallback only (Tiingo is primary — see tiingo.py and
PRD §5), so this does not block Phase 0. Revisit if/when a headless-browser
fetch path is added, or drop Stooq from the source list if it stays blocked.
No CSV-parsing logic is implemented yet either — writing it against a
hand-constructed sample (rather than a real captured response) would
violate this repo's "golden files come from real API responses" convention,
so both fetch and parse are deferred together.
"""

from agentic_fundamental_analyst.contracts.prices import PriceBar


async def fetch_daily_bars(ticker: str) -> list[PriceBar]:
    raise NotImplementedError(
        "Stooq's CSV endpoint now requires solving a JS proof-of-work "
        "challenge (confirmed blocked as of Phase 0, 2026-08); no headless-"
        "browser fetch path exists yet. See this module's docstring and "
        "PRD §5 (Stooq is backfill fallback only, not on the critical path)."
    )
