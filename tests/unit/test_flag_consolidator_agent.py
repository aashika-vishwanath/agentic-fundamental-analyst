from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.flag_consolidator import (
    flag_consolidator,
    run_flag_consolidator,
)
from agentic_fundamental_analyst.contracts.consolidation import FlagConsolidatorAgentOutput
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote


def _numeric_flag(metric: str, fiscal_year: int, description: str) -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        severity=Severity.MEDIUM,
        description=description,
        source=SourcedFigure(value=3.2, source="ratios." + metric, as_of=date(fiscal_year, 12, 31)),
    )


def _quote_flag(metric: str, fiscal_year: int, description: str) -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        severity=Severity.MEDIUM,
        description=description,
        source=SourcedQuote(text="quoted text", source="EDGAR:x", as_of=date(fiscal_year, 12, 31)),
    )


CAPEX_RATIO_FLAG = _numeric_flag(
    "capex_to_depreciation_ratio",
    2024,
    "Capex/D&A jumped to 4.3x driven by AI infrastructure buildout.",
)
CAPEX_MDNA_FLAG = _quote_flag(
    "non_gaap_gap_widening",
    2024,
    "MD&A discusses a significant AI infrastructure capital expenditure program.",
)
UNRELATED_FLAG = _numeric_flag("cash_conversion_ratio", 2023, "Cash conversion weakened.")


def test_agent_default_test_model_produces_valid_output_type():
    with flag_consolidator.override(model=TestModel()):
        result = flag_consolidator.run_sync("[]")
    assert isinstance(result.output, FlagConsolidatorAgentOutput)


async def test_run_flag_consolidator_groups_related_flags_by_index():
    flags = [CAPEX_RATIO_FLAG, CAPEX_MDNA_FLAG, UNRELATED_FLAG]
    scripted_output = {
        "groups": [
            {"flag_indices": [0, 1], "summary": "Same AI-buildout capex program flagged twice."}
        ]
    }
    with flag_consolidator.override(model=TestModel(custom_output_args=scripted_output)):
        consolidated = await run_flag_consolidator(flags)

    grouped = [c for c in consolidated if len(c.flags) == 2]
    assert len(grouped) == 1
    assert {id(f) for f in grouped[0].flags} == {id(CAPEX_RATIO_FLAG), id(CAPEX_MDNA_FLAG)}

    singletons = [c for c in consolidated if len(c.flags) == 1]
    assert len(singletons) == 1
    assert singletons[0].flags[0] == UNRELATED_FLAG


async def test_run_flag_consolidator_drops_invalid_and_duplicate_indices_without_losing_flags():
    flags = [CAPEX_RATIO_FLAG, CAPEX_MDNA_FLAG, UNRELATED_FLAG]
    scripted_output = {
        "groups": [
            {"flag_indices": [0, 99], "summary": "References an out-of-range index."},
            {"flag_indices": [0, 1], "summary": "Reuses index 0, already claimed above."},
        ]
    }
    with flag_consolidator.override(model=TestModel(custom_output_args=scripted_output)):
        consolidated = await run_flag_consolidator(flags)

    all_flags_in_output = [f for c in consolidated for f in c.flags]
    # Every input flag survives exactly once -- nothing lost, nothing duplicated.
    assert sorted(id(f) for f in all_flags_in_output) == sorted(id(f) for f in flags)


async def test_run_flag_consolidator_deduplicates_exact_matches_before_agent_sees_them():
    duplicate = _numeric_flag("capex_to_depreciation_ratio", 2024, "Same flag, different analyst.")
    flags = [CAPEX_RATIO_FLAG, duplicate]
    with flag_consolidator.override(model=TestModel(custom_output_args={"groups": []})):
        consolidated = await run_flag_consolidator(flags)

    all_flags_in_output = [f for c in consolidated for f in c.flags]
    assert len(all_flags_in_output) == 1


async def test_run_flag_consolidator_empty_input_yields_empty_output_without_calling_model():
    # No TestModel override installed -- proves the model is never invoked
    # for an empty flag list.
    consolidated = await run_flag_consolidator([])
    assert consolidated == []
