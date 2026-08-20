from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst import valuation
from agentic_fundamental_analyst.agents.valuation_interpreter import (
    run_valuation_interpreter,
    valuation_interpreter,
)
from agentic_fundamental_analyst.contracts.valuation import (
    PeerFinancials,
    ValuationAssumptions,
    ValuationResult,
)
from agentic_fundamental_analyst.contracts.valuation_interpreter import (
    ValuationInterpreterAgentOutput,
)

ASSUMPTIONS = ValuationAssumptions(
    risk_free_rate=0.042,
    risk_free_rate_as_of=date(2026, 8, 17),
    equity_risk_premium=0.055,
    discount_rate=0.097,
    terminal_growth=0.025,
)

CASH_FLOWS = [100.0, 110.0, 121.0]
DCF_RESULT = valuation.dcf(CASH_FLOWS, ASSUMPTIONS.discount_rate, ASSUMPTIONS.terminal_growth)

TARGET = PeerFinancials(
    ticker="TEST", price=224.0, shares_outstanding=10.0, revenue=1000.0, net_income=100.0,
    ebitda=None, total_debt=0.0, cash_and_equivalents=0.0,
)
PEER = PeerFinancials(
    ticker="PEER", price=181.0, shares_outstanding=10.0, revenue=900.0, net_income=100.0,
    ebitda=None, total_debt=0.0, cash_and_equivalents=0.0,
)
COMPS = valuation.peer_multiples(TARGET, [PEER])

RESULT = ValuationResult(
    ticker="TEST", assumptions=ASSUMPTIONS, dcf=DCF_RESULT, comps=COMPS, coverage_gaps=[]
)


def test_agent_default_test_model_produces_valid_output_type():
    with valuation_interpreter.override(model=TestModel()):
        result = valuation_interpreter.run_sync(RESULT.model_dump_json())
    assert isinstance(result.output, ValuationInterpreterAgentOutput)


async def test_run_valuation_interpreter_keeps_grounded_summary_citing_assumptions():
    base_pv = next(s for s in DCF_RESULT.scenarios if s.label == "base").present_value
    scripted = {
        "summary": (
            f"Assuming a discount rate of 9.7% (a 4.2% risk-free rate plus an "
            f"assumed 5.5% equity risk premium), the base-case DCF present value "
            f"is {base_pv:.4f}. The target's P/E of 22.4 sits above the peer "
            f"median of 18.1."
        )
    }
    with valuation_interpreter.override(model=TestModel(custom_output_args=scripted)):
        result = await run_valuation_interpreter(RESULT)

    assert "9.7" in result.summary
    assert result.coverage_gaps == []


async def test_run_valuation_interpreter_falls_back_on_fabricated_number():
    scripted = {"summary": "The DCF implies a wildly optimistic value of 8675309.0 per share."}
    with valuation_interpreter.override(model=TestModel(custom_output_args=scripted)):
        result = await run_valuation_interpreter(RESULT)

    assert result.summary != "The DCF implies a wildly optimistic value of 8675309.0 per share."
    assert any(g.reason == "numeric_grounding_check_failed" for g in result.coverage_gaps)


async def test_run_valuation_interpreter_grounds_per_scenario_bull_bear_rates():
    # DCFScenario.discount_rate/.terminal_growth differ per scenario (dcf()'s
    # +-100bps/+-50bps deltas around the base case) — the model legitimately
    # narrates these, not just ValuationAssumptions' base-case rate. Found
    # live during Phase 4 eval validation.
    bull = next(s for s in DCF_RESULT.scenarios if s.label == "bull")
    scripted = {
        "summary": f"The bull scenario assumes a {bull.discount_rate * 100:.1f}% discount rate."
    }
    with valuation_interpreter.override(model=TestModel(custom_output_args=scripted)):
        result = await run_valuation_interpreter(RESULT)

    assert "not pass the numeric-grounding check" not in result.summary


async def test_run_valuation_interpreter_grounds_number_cited_from_coverage_gap_reason():
    from agentic_fundamental_analyst.contracts.financials import CoverageGap

    result_with_gap = RESULT.model_copy(
        update={
            "coverage_gaps": [
                CoverageGap(field="peers", reason="insufficient peer data for SIC 7370")
            ]
        }
    )
    scripted = {"summary": "Peer comps are thin for SIC 7370, so rely on the DCF range."}
    with valuation_interpreter.override(model=TestModel(custom_output_args=scripted)):
        result = await run_valuation_interpreter(result_with_gap)

    assert "not pass the numeric-grounding check" not in result.summary


async def test_run_valuation_interpreter_handles_missing_dcf_and_comps():
    thin_result = ValuationResult(
        ticker="TEST", assumptions=ASSUMPTIONS, dcf=None, comps=None, coverage_gaps=[]
    )
    scripted = {
        "summary": (
            "No trailing DCF or peer comps are available for this ticker at this time."
        )
    }
    with valuation_interpreter.override(model=TestModel(custom_output_args=scripted)):
        result = await run_valuation_interpreter(thin_result)

    assert result.coverage_gaps == []
    assert "No trailing DCF" in result.summary
