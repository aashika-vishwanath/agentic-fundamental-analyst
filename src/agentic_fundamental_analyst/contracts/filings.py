from datetime import date

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap


class FilingMetadata(BaseModel):
    accession_number: str
    form: str
    filed_date: date
    period_of_report: date | None
    primary_document_url: str
    items: list[str]


class EightKItemSource(BaseModel):
    accession_number: str
    filed_date: date


class FilingSections(BaseModel):
    accession_number: str
    filed_date: date | None
    period_of_report: date | None
    item_1_business: str | None
    item_1a_risk_factors: str | None
    item_7_mdna: str | None
    item_9a_controls: str | None
    # Merged across a bounded lookback scan of recent 8-Ks (most-recent-wins
    # per item number) — no longer just the single latest 8-K. See
    # eightk_item_sources for per-item-number provenance (needed to derive a
    # fiscal_year for a flag grounded in one of these bodies).
    eightk_item_bodies: dict[str, str]
    eightk_item_sources: dict[str, EightKItemSource]
    coverage_gaps: list[CoverageGap]
