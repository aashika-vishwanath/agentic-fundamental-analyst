"""fetch_all(ticker) — the single entry point Phase 1's analysts will call.
Runs the SIC-exclusion intake check first and short-circuits before any
other fetch if the ticker is out of scope (PRD §7)."""

from datetime import date, timedelta

from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.prices import PriceHistory
from agentic_fundamental_analyst.contracts.transcripts import TranscriptInput
from agentic_fundamental_analyst.data.edgar import EdgarClient
from agentic_fundamental_analyst.data.fred import FredClient
from agentic_fundamental_analyst.data.tiingo import PriceClient

# Macro series pulled for every ticker (see .agents/references/free-data-sources.md §2)
_MACRO_SERIES_IDS = ["DGS10", "FEDFUNDS", "T10Y2Y"]

# FredClient.observations() defaults to full series history since inception
# (DGS10 back to 1962) when given no start date -- harmless on its own, but
# MemoSynthesisInput (Phase 5) carries macro_bundles whole, and the Macro
# Sensitivity Analyst's own prompt only ever asks for "current regime and
# recent direction," never a multi-decade history. Measured live (this
# session, real GOOGL data): unbounded macro_bundles alone was 1.3M chars
# (~527K of MemoSynthesisInput's 614K total input tokens, over Anthropic's
# 500K ITPM cap on its own) versus 121K tokens for a 5-year window -- 5 years
# chosen over a shorter window specifically to keep the 2020 near-zero-rate
# era and the 2022-2023 hiking cycle in view, which a 2-year window would cut
# off entirely and leave the Macro Analyst no "recent direction" story to
# tell from a flat, already-elevated plateau.
_MACRO_LOOKBACK = timedelta(days=365 * 5)


class TickerOutOfScope(Exception):
    def __init__(self, intake: TickerIntakeResult) -> None:
        self.intake = intake
        super().__init__(
            f"{intake.ticker} is out of scope: {intake.exclusion_reason} "
            f"(SIC {intake.sic_code} — {intake.sic_description})"
        )


async def fetch_all(
    ticker: str,
    price_start: date | None = None,
) -> tuple[
    TickerIntakeResult,
    FinancialStatementBundle,
    FilingSections,
    list[MacroSeriesBundle],
    PriceHistory,
    TranscriptInput | None,
]:
    """Gated on TickerIntakeResult.in_scope — raises TickerOutOfScope before
    any other network call if the ticker is a bank/insurer/REIT (PRD §7).

    Returns a 6-tuple as of Phase 4 (previously 5) — `intake` is now
    returned rather than discarded after the exclusion check, since Phase
    4's Sector/Macro agents need its sic_code/sic_description and this was
    already resolved internally on every call.
    """
    edgar = EdgarClient()
    intake = await edgar.get_ticker_intake(ticker)
    if not intake.in_scope:
        raise TickerOutOfScope(intake)

    financials = await edgar.get_financial_statement_bundle(ticker, intake.cik)
    filings = await edgar.get_filing_sections(intake.cik)
    transcript = await edgar.get_transcript_input(intake.cik)

    fred = FredClient()
    macro_start = date.today() - _MACRO_LOOKBACK
    macro_bundles = [
        await fred.observations(series_id, start=macro_start) for series_id in _MACRO_SERIES_IDS
    ]

    prices = await PriceClient().daily_prices(ticker, start=price_start)

    return intake, financials, filings, macro_bundles, prices, transcript
