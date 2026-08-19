from pydantic import BaseModel


class RatioResult(BaseModel):
    value: float | None
    reason: str | None = None  # populated only when value is None
