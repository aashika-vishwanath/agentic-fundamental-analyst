"""Eval dataset for the Valuation Interpreter (Phase 4).

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.valuation_interpreter
Passing bar (see .agents/plans/phase-4-sector-macro-valuation.md):
- ValuationGroundingEvaluator's `is_grounded` at 100% (holds by construction) and
  `fallback_triggered` at 100% False — the real quality signal.
- ExpectedCoverageGapPresent passes on the two *_unavailable cases.
- LLMJudge rubric (discount rate/terminal growth stated as disclosed assumptions, never as fact —
  the investment-memo-writing skill's Section 6 requirement verbatim) passes on at least 4/5
  (softest bar — never loosen the rubric to make a failure disappear, flag it instead).
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import VALUATION_INTERPRETER_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import (
    extract_numbers,
    summary_is_grounded,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.valuation import (
    PeerFinancials,
    ValuationAssumptions,
    ValuationResult,
)
from agentic_fundamental_analyst.contracts.valuation_interpreter import ValuationInterpreterOutput
from agentic_fundamental_analyst.valuation import dcf, peer_multiples

_ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2026, 8, 17),
    equity_risk_premium=0.055,
    discount_rate=0.097,
    terminal_growth=0.025,
)

_CASH_FLOWS = [100.0, 110.0, 121.0]
_DCF = dcf(_CASH_FLOWS, _ASSUMPTIONS.discount_rate, _ASSUMPTIONS.terminal_growth)

_TARGET = PeerFinancials(
    ticker="TEST", price=224.0, shares_outstanding=10.0, revenue=1000.0, net_income=100.0,
    ebitda=None, total_debt=0.0, cash_and_equivalents=0.0,
)
_PEER = PeerFinancials(
    ticker="PEER", price=181.0, shares_outstanding=10.0, revenue=900.0, net_income=100.0,
    ebitda=None, total_debt=0.0, cash_and_equivalents=0.0,
)
_COMPS = peer_multiples(_TARGET, [_PEER])

# --- bull_scenario_undefined_present_value: discount_rate close enough to
# terminal_growth that the bull leg (rate -1%, growth +0.5%) crosses the
# discount_rate <= terminal_growth boundary while base/bear stay valid.
# (Not "bear" — bear moves rate/growth in the *more conservative* direction,
# away from the boundary, so it's structurally the scenario LEAST likely to
# go undefined; this was mislabeled in the Phase 4 plan's case list and is
# corrected here — see the plan's Execution Deviations.)
_TIGHT_ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2026, 8, 17),
    equity_risk_premium=0.0,
    discount_rate=0.03,
    terminal_growth=0.025,
)
_TIGHT_DCF = dcf(_CASH_FLOWS, _TIGHT_ASSUMPTIONS.discount_rate, _TIGHT_ASSUMPTIONS.terminal_growth)


def _known_numbers_from_case(result: ValuationResult) -> set[float]:
    """Reimplemented independently from agents/valuation_interpreter.py's
    own _known_numbers_from_valuation — see evals/sector_analyst.py's
    analogous note."""
    known: set[float] = set()
    a = result.assumptions
    for value in (a.risk_free_rate, a.equity_risk_premium, a.discount_rate, a.terminal_growth):
        known.add(round(value, 4))
        known.add(round(value * 100, 4))
    if result.dcf is not None:
        for scenario in result.dcf.scenarios:
            known.add(round(scenario.discount_rate, 4))
            known.add(round(scenario.discount_rate * 100, 4))
            known.add(round(scenario.terminal_growth, 4))
            known.add(round(scenario.terminal_growth * 100, 4))
            if scenario.present_value is not None:
                known.add(round(scenario.present_value, 4))
    if result.comps is not None:
        for pm in (result.comps.target, *result.comps.peers):
            for value in (pm.pe_ratio, pm.ev_to_revenue, pm.ev_to_ebitda):
                if value is not None:
                    known.add(round(value, 4))
        for value in (
            result.comps.peer_median_pe,
            result.comps.peer_median_ev_to_revenue,
            result.comps.peer_median_ev_to_ebitda,
        ):
            if value is not None:
                known.add(round(value, 4))
    for gap in result.coverage_gaps:
        known.update(extract_numbers(gap.reason))
    return known


@dataclass
class ValuationGroundingEvaluator(Evaluator[ValuationResult, ValuationInterpreterOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[ValuationResult, ValuationInterpreterOutput, dict]
    ) -> dict[str, bool]:
        known = _known_numbers_from_case(ctx.inputs)
        return {
            "is_grounded": summary_is_grounded(ctx.output.summary, known),
            "fallback_triggered": any(
                g.reason == "numeric_grounding_check_failed" for g in ctx.output.coverage_gaps
            ),
        }


@dataclass
class ExpectedCoverageGapPresent(Evaluator[ValuationResult, ValuationInterpreterOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[ValuationResult, ValuationInterpreterOutput, dict]
    ) -> bool:
        expected_substring = (ctx.metadata or {}).get("expected_coverage_gap_substring")
        if expected_substring is None:
            return True
        return any(expected_substring in g.reason for g in ctx.output.coverage_gaps)


_SUMMARY_QUALITY_RUBRIC = (
    "The discount rate and terminal growth are stated explicitly as disclosed assumptions "
    "(e.g. 'assuming...', 'an assumed...', 'derived from a risk-free rate of X plus an assumed "
    "equity risk premium of Y'), never presented as established fact. If dcf is null, the "
    "summary relies on comps only and says DCF is unavailable rather than inventing scenario "
    "values; if comps is null, the summary relies on DCF only and says comps are unavailable "
    "rather than inventing a peer comparison. Neither gap is a violation if handled this way."
)

dataset = Dataset(
    name="valuation_interpreter",
    cases=[
        Case(
            name="dcf_and_comps_both_available",
            inputs=ValuationResult(
                ticker="TEST", assumptions=_ASSUMPTIONS, dcf=_DCF, comps=_COMPS, coverage_gaps=[]
            ),
        ),
        Case(
            name="bull_scenario_undefined_present_value",
            inputs=ValuationResult(
                ticker="TEST",
                assumptions=_TIGHT_ASSUMPTIONS,
                dcf=_TIGHT_DCF,
                comps=_COMPS,
                coverage_gaps=[],
            ),
        ),
        Case(
            name="comps_unavailable_dcf_only",
            inputs=ValuationResult(
                ticker="TEST",
                assumptions=_ASSUMPTIONS,
                dcf=_DCF,
                comps=None,
                coverage_gaps=[
                    CoverageGap(field="peers", reason="insufficient peer data for SIC 7370")
                ],
            ),
            metadata={"expected_coverage_gap_substring": "insufficient peer data"},
        ),
        Case(
            name="dcf_unavailable_comps_only",
            inputs=ValuationResult(
                ticker="TEST",
                assumptions=_ASSUMPTIONS,
                dcf=None,
                comps=_COMPS,
                coverage_gaps=[
                    CoverageGap(
                        field="trailing_free_cash_flows",
                        reason="fewer than 2 usable annual periods with both operating_cash_flow "
                        "and capex present",
                    )
                ],
            ),
            metadata={"expected_coverage_gap_substring": "fewer than 2 usable annual periods"},
        ),
        Case(
            name="both_unavailable_pure_coverage_gap",
            inputs=ValuationResult(
                ticker="TEST",
                assumptions=_ASSUMPTIONS,
                dcf=None,
                comps=None,
                coverage_gaps=[
                    CoverageGap(field="peers", reason="insufficient peer data for SIC 7370"),
                    CoverageGap(
                        field="trailing_free_cash_flows",
                        reason="fewer than 2 usable annual periods",
                    ),
                ],
            ),
            metadata={"expected_coverage_gap_substring": "insufficient peer data"},
        ),
    ],
    evaluators=[
        ValuationGroundingEvaluator(),
        ExpectedCoverageGapPresent(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=VALUATION_INTERPRETER_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.valuation_interpreter import run_valuation_interpreter

    report = dataset.evaluate_sync(run_valuation_interpreter)
    report.print(include_input=False, include_output=True, include_durations=True)
