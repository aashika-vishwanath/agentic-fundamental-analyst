from datetime import date

from pydantic import BaseModel


class SourcedFigure(BaseModel):
    value: float
    source: str
    as_of: date


class SourcedQuote(BaseModel):
    text: str
    source: str
    as_of: date
