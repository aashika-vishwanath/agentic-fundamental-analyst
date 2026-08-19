from enum import Enum

from pydantic import BaseModel


class ExcludedSector(str, Enum):
    BANK = "bank"
    INSURER = "insurer"
    REIT = "reit"


class TickerIntakeResult(BaseModel):
    ticker: str
    cik: str
    sic_code: str
    sic_description: str
    in_scope: bool
    exclusion_reason: ExcludedSector | None
