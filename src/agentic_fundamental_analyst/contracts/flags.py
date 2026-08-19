from enum import Enum

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Flag(BaseModel):
    metric: str
    fiscal_year: int
    fiscal_period: str
    severity: Severity
    description: str
    source: SourcedFigure
