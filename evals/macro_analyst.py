"""Eval dataset for the Macro Sensitivity Analyst (Phase 4).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.macro_analyst
Passing bar (see .agents/plans/phase-4-sector-macro-valuation.md):
- MacroGroundingEvaluator's `is_grounded` at 100% (holds by construction — see
  agents/macro.py::run_macro_sensitivity_analyst) and `fallback_triggered` at 100% False across
  all cases — the real quality signal.
- LLMJudge rubric passes on at least 3/4 (softest bar — never loosen the rubric to make a failure
  disappear, flag it instead).
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import MACRO_SENSITIVITY_ANALYST_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import summary_is_grounded
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle, MacroSeriesPoint
from agentic_fundamental_analyst.contracts.macro_analyst import (
    CompanyMacroProfile,
    MacroAnalystInput,
    MacroAnalystOutput,
)

_SIC_DESC = "Services-Computer Programming, Data Processing, Etc."


def _bundle(series_id: str, values: list[float | None]) -> MacroSeriesBundle:
    return MacroSeriesBundle(
        series_id=series_id,
        points=[
            MacroSeriesPoint(obs_date=date(2026, 8, 1 + i), value=v) for i, v in enumerate(values)
        ],
    )


# --- rising_rate_regime: 10Y climbing, elevated Fed funds, inverted 2s10s ---
_RISING = [
    _bundle("DGS10", [3.80, 3.95, 4.10, 4.30]),
    _bundle("FEDFUNDS", [5.00, 5.10, 5.25, 5.25]),
    _bundle("T10Y2Y", [-0.20, -0.15, -0.05, 0.05]),
]

# --- easing_regime: rates coming down from a peak ---
_EASING = [
    _bundle("DGS10", [4.50, 4.20, 3.90, 3.70]),
    _bundle("FEDFUNDS", [5.50, 5.25, 4.75, 4.25]),
    _bundle("T10Y2Y", [0.30, 0.40, 0.50, 0.55]),
]

# --- flat_stable_regime: barely moving, no drama warranted ---
_FLAT = [
    _bundle("DGS10", [4.00, 4.02, 3.99, 4.01]),
    _bundle("FEDFUNDS", [4.50, 4.50, 4.50, 4.50]),
    _bundle("T10Y2Y", [0.20, 0.21, 0.19, 0.20]),
]

# --- dgs10_outage: the risk-free-rate series is entirely null (FRED outage) ---
_OUTAGE = [
    _bundle("DGS10", [None, None, None, None]),
    _bundle("FEDFUNDS", [4.50, 4.50, 4.50, 4.50]),
    _bundle("T10Y2Y", [0.20, 0.21, 0.19, 0.20]),
]

_LEVERED_PROFILE = CompanyMacroProfile(
    ticker="TEST",
    sic_description=_SIC_DESC,
    latest_revenue=1000.0,
    latest_total_debt=800.0,  # high leverage — rate sensitivity should be discussable
    revenue_cagr=0.03,
)


def _known_numbers_from_case(payload: MacroAnalystInput) -> set[float]:
    """Reimplemented independently from agents/macro.py's own
    _known_numbers_from_macro — see evals/sector_analyst.py's analogous note."""
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
            known.add(round(value * 100, 4))
    return known


@dataclass
class MacroGroundingEvaluator(Evaluator[MacroAnalystInput, MacroAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[MacroAnalystInput, MacroAnalystOutput, dict]
    ) -> dict[str, bool]:
        known = _known_numbers_from_case(ctx.inputs)
        return {
            "is_grounded": summary_is_grounded(ctx.output.summary, known),
            "fallback_triggered": any(
                g.reason == "numeric_grounding_check_failed" for g in ctx.output.coverage_gaps
            ),
        }


_SUMMARY_QUALITY_RUBRIC = (
    "The summary describes the actual rate/macro regime shown in the input series (levels and "
    "direction), and ties it to something specific about this company's own profile (its "
    "leverage via latest_total_debt, or growth sensitivity via revenue_cagr) rather than writing "
    "generic 'rates matter to all companies' commentary that could apply to any ticker. If a "
    "series is entirely null, the summary says so rather than inventing a level for it. A calm, "
    "low-drama summary for a genuinely flat/stable regime is NOT a violation."
)

dataset = Dataset(
    name="macro_analyst",
    cases=[
        Case(
            name="rising_rate_regime",
            inputs=MacroAnalystInput(macro_bundles=_RISING, profile=_LEVERED_PROFILE),
        ),
        Case(
            name="easing_regime",
            inputs=MacroAnalystInput(macro_bundles=_EASING, profile=_LEVERED_PROFILE),
        ),
        Case(
            name="flat_stable_regime_no_drama",
            inputs=MacroAnalystInput(macro_bundles=_FLAT, profile=_LEVERED_PROFILE),
        ),
        Case(
            name="dgs10_outage_coverage_gap",
            inputs=MacroAnalystInput(macro_bundles=_OUTAGE, profile=_LEVERED_PROFILE),
        ),
    ],
    evaluators=[
        MacroGroundingEvaluator(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=MACRO_SENSITIVITY_ANALYST_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.macro import run_macro_sensitivity_analyst

    async def _run(payload: MacroAnalystInput) -> MacroAnalystOutput:
        return await run_macro_sensitivity_analyst(payload.macro_bundles, payload.profile)

    report = dataset.evaluate_sync(_run)
    report.print(include_input=False, include_output=True, include_durations=True)
