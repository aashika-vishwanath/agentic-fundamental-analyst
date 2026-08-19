"""fetch_all(ticker) — the single entry point Phase 1's analysts will call.
Runs the SIC-exclusion intake check first and short-circuits before any
other fetch if the ticker is out of scope (PRD §7)."""

from datetime import date

from agentic_fundamental_analyst.contracts.filings import FilingSections
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle
from agentic_fundamental_analyst.contracts.intake import TickerIntakeResult
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.prices import PriceHistory
from agentic_fundamental_analyst.data.edgar import EdgarClient
from agentic_fundamental_analyst.data.fred import FredClient
from agentic_fundamental_analyst.data.tiingo import PriceClient

# Macro series pulled for every ticker (see .agents/references/free-data-sources.md §2)
_MACRO_SERIES_IDS = ["DGS10", "FEDFUNDS", "T10Y2Y"]


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
    FinancialStatementBundle,
    FilingSections,
    list[MacroSeriesBundle],
    PriceHistory,
]:
    """Gated on TickerIntakeResult.in_scope — raises TickerOutOfScope before
    any other network call if the ticker is a bank/insurer/REIT (PRD §7).
    """
    edgar = EdgarClient()
    intake = await edgar.get_ticker_intake(ticker)
    if not intake.in_scope:
        raise TickerOutOfScope(intake)

    financials = await edgar.get_financial_statement_bundle(ticker, intake.cik)
    filings = await edgar.get_filing_sections(intake.cik)

    fred = FredClient()
    macro_bundles = [
        await fred.observations(series_id, start=price_start) for series_id in _MACRO_SERIES_IDS
    ]

    prices = await PriceClient().daily_prices(ticker, start=price_start)

    return financials, filings, macro_bundles, prices
