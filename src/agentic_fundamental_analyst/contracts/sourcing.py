from datetime import date

from pydantic import BaseModel


class SourcedFigure(BaseModel):
    value: float
    source: str
    as_of: date
