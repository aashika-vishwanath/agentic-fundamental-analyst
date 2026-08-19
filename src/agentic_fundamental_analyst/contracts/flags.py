from enum import Enum

from pydantic import BaseModel

from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote


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
    # A numeric-ratio flag (Financial Statements Analyst) carries a SourcedFigure;
    # a prose-derived flag (Filings/Transcript Analyst) carries a SourcedQuote —
    # a fabricated numeric value for a non-numeric claim would be hollow typing.
    source: SourcedFigure | SourcedQuote
