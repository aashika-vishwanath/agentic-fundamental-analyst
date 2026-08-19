from typing import Literal

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Flag, Severity

TranscriptFlagMetric = Literal["management_tone_or_guidance_concern"]


class TranscriptFlagCandidate(BaseModel):
    metric: TranscriptFlagMetric
    quoted_evidence: str
    severity: Severity
    description: str


class TranscriptAnalystAgentOutput(BaseModel):
    summary: str
    flag_candidates: list[TranscriptFlagCandidate]


class TranscriptAnalystOutput(BaseModel):
    ticker: str
    summary: str | None  # None only when the stage never ran (no transcript found)
    flags: list[Flag]
    coverage_gaps: list[CoverageGap]
    dropped_candidates: list[str] = []
