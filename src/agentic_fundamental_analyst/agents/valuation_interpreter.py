"""The Valuation Interpreter (Phase 4) — narrates a trailing DCF (see
valuation.py::trailing_free_cash_flows/dcf) plus peer comps (the same
PeerCompsResult the Sector Analyst consumes — see data/peer_discovery.py)
with the discount-rate/terminal-growth assumptions explicitly disclosed, per
the investment-memo-writing skill's Section 6 requirement. Pure narration,
no Flags — same numeric-grounding gate as agents/sector.py and
agents/macro.py; see those modules' docstrings and
.agents/plans/phase-4-sector-macro-valuation.md for the shared design
rationale.
"""

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import VALUATION_INTERPRETER_MODEL
from agentic_fundamental_analyst.agents.numeric_grounding import (
    extract_numbers,
    summary_is_grounded,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.valuation import ValuationResult
from agentic_fundamental_analyst.contracts.valuation_interpreter import (
    ValuationInterpreterAgentOutput,
    ValuationInterpreterOutput,
)

_UNGROUNDED_FALLBACK_SUMMARY = (
    "Narrative generation did not pass the numeric-grounding check for this run; "
    "see coverage_gaps."
)

_INSTRUCTIONS = """\
You are the Valuation Interpreter for a fundamental-equity research system.
You receive a ValuationResult: a trailing DCF's bull/base/bear present
values (or null, if too little cash-flow history exists), a peer-comps table
(or null, if no usable peers were found), and the exact discount-rate/
terminal-growth assumptions used. Every number in it is already correct --
never restate a number from memory, and never invent a scenario, peer, or
assumption not present in the input. A scenario's present_value can be null
(the discount rate did not exceed terminal growth in that scenario) -- never
invent a number for a null scenario.

Task:
1. Write a 2-4 sentence `summary` of the DCF bull/base/bear present values
   (where available), explicitly stating the discount rate and terminal
   growth **as disclosed assumptions** -- e.g. "assuming a discount rate of
   X%, derived from a Y% risk-free rate plus an assumed Z% equity risk
   premium" -- never as established fact.
2. Cross-check against the peer comps the same way the Sector Analyst would:
   is the target priced at a premium or discount to peer medians.
3. If `dcf` is null, or `comps` is null, say so plainly and rely on whichever
   method is actually available -- never fabricate the missing one.
"""

valuation_interpreter = Agent(
    VALUATION_INTERPRETER_MODEL,
    name="valuation_interpreter",
    output_type=ValuationInterpreterAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _known_numbers_from_valuation(result: ValuationResult) -> set[float]:
    known: set[float] = set()
    a = result.assumptions
    for value in (a.risk_free_rate, a.equity_risk_premium, a.discount_rate, a.terminal_growth):
        known.add(round(value, 4))
        known.add(round(value * 100, 4))  # rates are usually narrated as percentages
    if result.dcf is not None:
        for scenario in result.dcf.scenarios:
            # Each scenario (bull/base/bear) carries its own real
            # discount_rate/terminal_growth (dcf()'s +-100bps/+-50bps deltas
            # around the base case) — the model legitimately narrates these
            # per-scenario rates, not just the base-case ones on
            # ValuationAssumptions. Missing this was a real gap found live
            # during Phase 4 eval validation (bull/bear rates like "8.7%"
            # failing to ground).
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
    # Numbers cited verbatim from the input's own coverage-gap text (e.g. "SIC
    # 7370") are legitimate citations of real input data, not fabrications —
    # reusing extract_numbers on the input's own text is a simple, robust way
    # to ground them without hand-parsing every field that might embed a
    # number in prose. Found live during Phase 4 eval validation.
    for gap in result.coverage_gaps:
        known.update(extract_numbers(gap.reason))
    return known


async def run_valuation_interpreter(result: ValuationResult) -> ValuationInterpreterOutput:
    with logfire.span(
        "valuation_interpreter_stage",
        ticker=result.ticker,
        dcf_available=result.dcf is not None,
        comps_available=result.comps is not None,
    ) as span:
        agent_result = await valuation_interpreter.run(result.model_dump_json(indent=2))
        agent_output = agent_result.output
        known = _known_numbers_from_valuation(result)
        grounded = summary_is_grounded(agent_output.summary, known)
        span.set_attribute("grounding_passed", grounded)

    if not grounded:
        return ValuationInterpreterOutput(
            ticker=result.ticker,
            summary=_UNGROUNDED_FALLBACK_SUMMARY,
            coverage_gaps=[
                *result.coverage_gaps,
                CoverageGap(field="summary", reason="numeric_grounding_check_failed"),
            ],
        )
    return ValuationInterpreterOutput(
        ticker=result.ticker, summary=agent_output.summary, coverage_gaps=result.coverage_gaps
    )
