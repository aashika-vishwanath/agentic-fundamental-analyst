from datetime import date
from typing import Literal

from pydantic import BaseModel


class PriceBar(BaseModel):
    bar_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adj_close: float


class PriceHistory(BaseModel):
    ticker: str
    source: Literal["tiingo", "stooq"]
    bars: list[PriceBar]
