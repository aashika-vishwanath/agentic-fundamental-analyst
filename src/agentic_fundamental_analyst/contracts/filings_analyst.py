from typing import Literal

from pydantic import BaseModel, model_validator

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Flag, Severity

FilingSection = Literal[
    "item_1_business",
    "item_1a_risk_factors",
    "item_7_mdna",
    "item_9a_controls",
    "eightk_item_body",
]

FilingFlagMetric = Literal[
    "non_gaap_gap_widening",  # checklist #8
    "recurring_one_time_items",  # checklist #9 — partial coverage, single-10-K visibility only
    "auditor_change",  # checklist #11
    "officer_turnover",  # checklist #12
    "material_weakness",  # checklist #13
    "going_concern_language",  # checklist #14 — partial coverage, Item 8 audit opinion not parsed
    "restatement",  # checklist #15
]


class FilingFlagCandidate(BaseModel):
    metric: FilingFlagMetric
    section: FilingSection
    eightk_item_number: str | None = None
    quoted_evidence: str
    severity: Severity
    description: str

    @model_validator(mode="after")
    def _eightk_item_number_required_iff_eightk_section(self) -> "FilingFlagCandidate":
        if self.section == "eightk_item_body" and self.eightk_item_number is None:
            raise ValueError("eightk_item_number is required when section == 'eightk_item_body'")
        if self.section != "eightk_item_body" and self.eightk_item_number is not None:
            raise ValueError(
                "eightk_item_number must be omitted unless section == 'eightk_item_body'"
            )
        return self


class FilingsAnalystAgentOutput(BaseModel):
    summary: str
    flag_candidates: list[FilingFlagCandidate]


class FilingsAnalystOutput(BaseModel):
    ticker: str
    summary: str
    flags: list[Flag]
    coverage_gaps: list[CoverageGap]
    dropped_candidates: list[str] = []
