from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.macro import (
    _known_numbers_from_macro,
    macro_sensitivity_analyst,
    run_macro_sensitivity_analyst,
)
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.macro_analyst import (
    CompanyMacroProfile,
    MacroAnalystAgentOutput,
    MacroAnalystInput,
)

MACRO_BUNDLES = [
    MacroSeriesBundle(
        series_id="DGS10",
        points=[
            MacroSeriesPoint(obs_date=date(2026, 8, 17), value=4.20),
            MacroSeriesPoint(obs_date=date(2026, 8, 18), value=None),
        ],
    ),
    MacroSeriesBundle(
        series_id="FEDFUNDS", points=[MacroSeriesPoint(obs_date=date(2026, 8, 17), value=5.25)]
    ),
]

PROFILE = CompanyMacroProfile(
    ticker="TEST",
    sic_description="Services-Computer Programming, Data Processing, Etc.",
    latest_revenue=1000.0,
    latest_total_debt=200.0,
    revenue_cagr=0.08,
)


def test_agent_default_test_model_produces_valid_output_type():
    payload = MacroAnalystInput(macro_bundles=MACRO_BUNDLES, profile=PROFILE)
    with macro_sensitivity_analyst.override(model=TestModel()):
        result = macro_sensitivity_analyst.run_sync(payload.model_dump_json())
    assert isinstance(result.output, MacroAnalystAgentOutput)


def test_known_numbers_includes_series_values_and_profile_fields():
    payload = MacroAnalystInput(macro_bundles=MACRO_BUNDLES, profile=PROFILE)
    known = _known_numbers_from_macro(payload)
    assert 4.20 in known
    assert 5.25 in known
    assert 1000.0 in known
    assert 200.0 in known
    assert 0.08 in known
    assert 8.0 in known  # CAGR narrated as a percent


async def test_run_macro_sensitivity_analyst_keeps_grounded_summary():
    scripted = {"summary": "The 10Y yield sits at 4.2% with Fed funds at 5.25%."}
    with macro_sensitivity_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_macro_sensitivity_analyst(MACRO_BUNDLES, PROFILE)

    assert "4.2" in result.summary
    assert result.coverage_gaps == []


async def test_run_macro_sensitivity_analyst_falls_back_on_fabricated_number():
    scripted = {"summary": "The 10Y yield has spiked to an alarming 8675309.0%."}
    with macro_sensitivity_analyst.override(model=TestModel(custom_output_args=scripted)):
        result = await run_macro_sensitivity_analyst(MACRO_BUNDLES, PROFILE)

    assert result.summary != "The 10Y yield has spiked to an alarming 8675309.0%."
    assert any(g.reason == "numeric_grounding_check_failed" for g in result.coverage_gaps)
