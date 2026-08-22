"""The orchestrator (Phase 5) — run_memo_pipeline(ticker), PRD §4's fixed
pipeline diagram made real. Deterministic wiring only: fetch_all() -> the
three Stage-2 analysts (parallel) -> exact-dedup + Flag Consolidator ->
Investigator x N (parallel) -> peer discovery + valuation math ->
Sector/Macro/Valuation Interpreter (parallel) -> Synthesizer draft ->
Red-Team -> Synthesizer resolve. No judgment happens here — every decision
already lives inside a typed agent output or a deterministic math function;
this function's only job is sequencing and typed-boundary assembly.

CLAUDE.md hard constraint: no orchestrator/router agent, no dynamic routing —
every run executes every stage in this fixed order.
"""

import asyncio

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.filings import run_filings_analyst
from agentic_fundamental_analyst.agents.financial_statements import run_financial_statements_analyst
from agentic_fundamental_analyst.agents.flag_consolidator import run_flag_consolidator
from agentic_fundamental_analyst.agents.investigator import run_investigations
from agentic_fundamental_analyst.agents.macro import run_macro_sensitivity_analyst
from agentic_fundamental_analyst.agents.red_team import run_red_team
from agentic_fundamental_analyst.agents.sector import run_sector_analyst
from agentic_fundamental_analyst.agents.synthesizer_draft import run_synthesizer_draft
from agentic_fundamental_analyst.agents.synthesizer_resolve import run_synthesizer_resolve
from agentic_fundamental_analyst.agents.transcript import run_transcript_analyst
from agentic_fundamental_analyst.agents.valuation_interpreter import run_valuation_interpreter
from agentic_fundamental_analyst.contracts.memo import Memo
from agentic_fundamental_analyst.contracts.synthesis import (
    MemoSynthesisInput,
    RedTeamInput,
    SynthesizerResolveInput,
)
from agentic_fundamental_analyst.contracts.valuation import ValuationResult
from agentic_fundamental_analyst.data.fetch import fetch_all
from agentic_fundamental_analyst.data.peer_discovery import discover_sector_peers
from agentic_fundamental_analyst.ratios import build_company_macro_profile, compute_trend_bundle
from agentic_fundamental_analyst.valuation import (
    build_valuation_assumptions,
    dcf,
    trailing_free_cash_flows,
)


class ValuationAssumptionsUnavailable(Exception):
    """Raised only when FRED's DGS10 series is entirely unavailable (every
    observation null) -- a full data-source outage, not a routine coverage
    gap. Mirrors data/peer_discovery.py::PeerDiscoveryError's precedent: a
    real ticker essentially always has at least one real DGS10 observation,
    so a fully-null bundle signals a genuine system/provider problem, not
    something to route around by threading a phantom
    `ValuationAssumptions | None` through ValuationResult, the Valuation
    Interpreter's grounding logic, and MemoSynthesisInput -- none of which
    support that today, and widening them is out of this phase's scope (it
    would need its own eval re-verification). Revisit if this proves too
    strict in practice (e.g. by widening ValuationResult.assumptions then)."""


async def run_memo_pipeline(ticker: str) -> Memo:
    # Stage 0-1: deterministic fetch. Propagates TickerOutOfScope unchanged
    # for an excluded-sector ticker, before any agent runs.
    intake, financials, filings, macro_bundles, prices, transcript = await fetch_all(ticker)
    latest_bar = max(prices.bars, key=lambda b: b.bar_date)

    # Stage 2: the three Stage-2 analysts, parallel.
    financial_out, filings_out, transcript_out = await asyncio.gather(
        run_financial_statements_analyst(financials),
        run_filings_analyst(ticker, filings),
        run_transcript_analyst(ticker, transcript),
    )

    # Stage 3: exact-dedup (inside run_flag_consolidator) + semantic merge.
    consolidated = await run_flag_consolidator(
        financial_out.flags + filings_out.flags + transcript_out.flags
    )

    # Stage 4: the Investigator, up to max_investigations flags in parallel.
    investigations, investigation_gaps = await run_investigations(consolidated)

    # Stage 5 setup: peer discovery (once, shared by Sector + Valuation
    # Interpreter) and deterministic valuation math.
    peer_data = await discover_sector_peers(
        ticker, intake.cik, intake.sic_code, intake.sic_description, latest_bar.close
    )
    assumptions = build_valuation_assumptions(macro_bundles)
    if assumptions is None:
        raise ValuationAssumptionsUnavailable(
            f"{ticker}: FRED DGS10 series returned no usable observation -- cannot "
            "build a discount rate for the Valuation stage"
        )
    flows = trailing_free_cash_flows(financials)
    dcf_result = (
        dcf(flows, assumptions.discount_rate, assumptions.terminal_growth)
        if flows is not None
        else None
    )
    valuation_result = ValuationResult(
        ticker=ticker,
        assumptions=assumptions,
        dcf=dcf_result,
        comps=peer_data.comps,
        coverage_gaps=peer_data.coverage_gaps,
    )
    profile = build_company_macro_profile(ticker, intake.sic_description, financials)

    # Stage 5: Sector / Macro / Valuation Interpreter, parallel.
    sector_out, macro_out, valuation_out = await asyncio.gather(
        run_sector_analyst(peer_data),
        run_macro_sensitivity_analyst(macro_bundles, profile),
        run_valuation_interpreter(valuation_result),
    )

    # Stage 6: assemble the typed synthesis input (code-owned coverage_gaps union).
    synthesis_input = MemoSynthesisInput(
        ticker=ticker,
        intake=intake,
        filings=filings,
        ratio_trend=compute_trend_bundle(financials),
        financials=financials,
        latest_price=latest_bar.close,
        latest_price_date=latest_bar.bar_date,
        macro_bundles=macro_bundles,
        valuation_result=valuation_result,
        financial_analyst_summary=financial_out.summary,
        filings_analyst_summary=filings_out.summary,
        transcript_analyst_summary=transcript_out.summary,
        sector_summary=sector_out.summary,
        macro_summary=macro_out.summary,
        valuation_summary=valuation_out.summary,
        consolidated_flags=consolidated,
        investigations=investigations,
        coverage_gaps=[
            *financial_out.coverage_gaps,
            *filings_out.coverage_gaps,
            *transcript_out.coverage_gaps,
            *investigation_gaps,
            *sector_out.coverage_gaps,
            *macro_out.coverage_gaps,
            *valuation_out.coverage_gaps,
        ],
    )

    # Stage 7: draft -> red-team -> resolve.
    draft = await run_synthesizer_draft(synthesis_input)
    red_team_result = await run_red_team(RedTeamInput(draft=draft, synthesis_input=synthesis_input))
    memo = await run_synthesizer_resolve(
        SynthesizerResolveInput(
            draft=draft, red_team=red_team_result, synthesis_input=synthesis_input
        )
    )
    return memo
