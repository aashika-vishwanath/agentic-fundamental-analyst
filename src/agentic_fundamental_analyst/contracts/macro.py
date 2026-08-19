from datetime import date

from pydantic import BaseModel


class MacroSeriesPoint(BaseModel):
    obs_date: date
    value: float | None


class MacroSeriesBundle(BaseModel):
    series_id: str
    points: list[MacroSeriesPoint]
