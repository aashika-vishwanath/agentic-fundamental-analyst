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


class FilingSections(BaseModel):
    accession_number: str
    item_1_business: str | None
    item_1a_risk_factors: str | None
    item_7_mdna: str | None
    eightk_item_bodies: dict[str, str]
    coverage_gaps: list[CoverageGap]
