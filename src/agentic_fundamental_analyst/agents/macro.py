"""The Macro Sensitivity Analyst (Phase 4) — narrates the current rate/macro
regime (FRED DGS10/FEDFUNDS/T10Y2Y) and its relevance to one specific
company's profile. Pure narration, no Flags — same numeric-grounding gate
as the Sector Analyst (agents/sector.py); see that module's docstring and
.agents/plans/phase-4-sector-macro-valuation.md for the shared design
rationale.
"""

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import MACRO_SENSITIVITY_ANALYST_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import summary_is_grounded
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.macro_analyst import (
    CompanyMacroProfile,
    MacroAnalystAgentOutput,
    MacroAnalystInput,
    MacroAnalystOutput,
)

_UNGROUNDED_FALLBACK_SUMMARY = (
    "Narrative generation did not pass the numeric-grounding check for this run; "
    "see coverage_gaps."
)

_INSTRUCTIONS = """\
You are the Macro Sensitivity Analyst for a fundamental-equity research
system. You receive a MacroAnalystInput: a handful of FRED macro series
(10-year Treasury yield, effective Fed funds rate, 10Y-2Y spread) and a
small CompanyMacroProfile (this company's SIC description, latest revenue,
latest total debt, and revenue CAGR where available). Every number in it is
already correct -- never restate a value from memory, and never invent a
macro series or company figure not present in the input. A None field in
the profile means that figure is unavailable -- never treat it as zero, and
never invent a value for it.

Task:
1. Write a 2-4 sentence `summary` of the current rate/macro regime (levels
   and recent direction across the supplied series) and *why it specifically
   matters to this company* -- e.g. leverage exposure via total debt, or
   growth-vs-rate sensitivity via revenue CAGR. Never write generic "rates
   matter to all companies" commentary that could apply to any ticker.
2. A flat, stable regime with no notable company-specific sensitivity is a
   valid, expected outcome -- do not manufacture drama or urgency that isn't
   supported by the actual series levels.
3. If a series' points are entirely null (a data-source gap), say so rather
   than fabricating a level for it.
"""

macro_sensitivity_analyst = Agent(
    MACRO_SENSITIVITY_ANALYST_MODEL,
    name="macro_sensitivity_analyst",
    output_type=MacroAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _known_numbers_from_macro(payload: MacroAnalystInput) -> set[float]:
    known: set[float] = set()
    for bundle in payload.macro_bundles:
        for point in bundle.points:
            if point.value is not None:
                known.add(round(point.value, 4))
    for value in (
        payload.profile.latest_revenue,
        payload.profile.latest_total_debt,
        payload.profile.revenue_cagr,
    ):
        if value is not None:
            known.add(round(value, 4))
            known.add(round(value * 100, 4))  # CAGR is often narrated as a percent
    return known


async def run_macro_sensitivity_analyst(
    macro_bundles: list[MacroSeriesBundle], profile: CompanyMacroProfile
) -> MacroAnalystOutput:
    payload = MacroAnalystInput(macro_bundles=macro_bundles, profile=profile)
    with logfire.span("macro_sensitivity_analyst_stage", ticker=profile.ticker) as span:
        result = await macro_sensitivity_analyst.run(payload.model_dump_json(indent=2))
        agent_output = result.output
        known = _known_numbers_from_macro(payload)
        grounded = summary_is_grounded(agent_output.summary, known)
        span.set_attribute("grounding_passed", grounded)

    if not grounded:
        return MacroAnalystOutput(
            ticker=profile.ticker,
            summary=_UNGROUNDED_FALLBACK_SUMMARY,
            coverage_gaps=[
                CoverageGap(field="summary", reason="numeric_grounding_check_failed"),
            ],
        )
    return MacroAnalystOutput(
        ticker=profile.ticker, summary=agent_output.summary, coverage_gaps=[]
    )
