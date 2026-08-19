from datetime import date

from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote


def test_flag_source_union_round_trips_sourced_figure():
    flag = Flag(
        metric="capex_to_depreciation_ratio",
        fiscal_year=2024,
        fiscal_period="FY",
        severity=Severity.HIGH,
        description="d",
        source=SourcedFigure(
            value=3.2, source="ratios.capex_to_depreciation_ratio", as_of=date(2024, 12, 31)
        ),
    )
    round_tripped = Flag.model_validate_json(flag.model_dump_json())
    assert isinstance(round_tripped.source, SourcedFigure)
    assert round_tripped.source.value == 3.2


def test_flag_source_union_round_trips_sourced_quote():
    flag = Flag(
        metric="going_concern_language",
        fiscal_year=2024,
        fiscal_period="FY",
        severity=Severity.HIGH,
        description="d",
        source=SourcedQuote(
            text="substantial doubt about our ability to continue as a going concern",
            source="EDGAR:0001-24-000001:item_7_mdna",
            as_of=date(2024, 12, 31),
        ),
    )
    round_tripped = Flag.model_validate_json(flag.model_dump_json())
    assert isinstance(round_tripped.source, SourcedQuote)
    assert "going concern" in round_tripped.source.text
