from datetime import date

from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.flags import deduplicate_exact_flags


def _flag(metric: str, fiscal_year: int, fiscal_period: str = "FY") -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        severity=Severity.MEDIUM,
        description="d",
        source=SourcedFigure(value=1.0, source="s", as_of=date(fiscal_year, 12, 31)),
    )


def test_dedup_keeps_first_occurrence_of_same_metric_period():
    a = _flag("capex_to_depreciation_ratio", 2024)
    b = _flag("capex_to_depreciation_ratio", 2024)  # same key, different object
    c = _flag("cash_conversion_ratio", 2024)

    result = deduplicate_exact_flags([a, b, c])

    assert result == [a, c]


def test_dedup_distinguishes_fiscal_period():
    a = _flag("days_sales_outstanding", 2024, "FY")
    b = _flag("days_sales_outstanding", 2024, "8K")

    result = deduplicate_exact_flags([a, b])

    assert result == [a, b]


def test_dedup_empty_input_yields_empty_output():
    assert deduplicate_exact_flags([]) == []
