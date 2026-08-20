"""Deterministic valuation math — DCF and self-built peer multiples.
Arithmetic on disclosed/typed inputs only; interpreting the result is the
Valuation Interpreter agent's job (Phase 4), not this module's (PRD §4).
"""

import statistics

from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle
from agentic_fundamental_analyst.contracts.macro import MacroSeriesBundle
from agentic_fundamental_analyst.contracts.valuation import (
    DCFResult,
    DCFScenario,
    PeerCompsResult,
    PeerFinancials,
    PeerMultiples,
    ValuationAssumptions,
)

_BULL_RATE_DELTA = -0.01
_BULL_GROWTH_DELTA = 0.005
_BEAR_RATE_DELTA = 0.01
_BEAR_GROWTH_DELTA = -0.005

# Phase 4 — fixed, disclosed assumptions (investment-memo-writing skill §1
# Section 6: "discount rate explicitly sourced... stated as an assumption
# not a fact"). No free source exists for either, so both are conventional,
# defensible round numbers rather than derived/fitted per ticker:
# - 5.5%: roughly the historical range of Damodaran-style implied US equity
#   risk premiums (~4-5.5%).
# - 2.5%: roughly long-run nominal-GDP-ish terminal growth, comfortably
#   below any plausible discount rate so dcf()'s present_value=None guard
#   (discount_rate <= terminal_growth) is not a live concern in practice.
# Revisit only if live validation shows systematically off DCF output — not
# something to tune per-ticker (see Phase 4 plan NOTES).
_EQUITY_RISK_PREMIUM = 0.055
_TERMINAL_GROWTH_ASSUMPTION = 0.025


def _present_value(
    cash_flows: list[float], discount_rate: float, terminal_growth: float
) -> float | None:
    """Sum of discounted projected cash flows plus a Gordon-growth terminal
    value discounted back from the final projection year. None if the
    discount rate doesn't exceed terminal growth (undefined/negative
    terminal value, not a real scenario)."""
    if discount_rate <= terminal_growth or not cash_flows:
        return None
    pv_explicit = sum(
        cf / (1 + discount_rate) ** t for t, cf in enumerate(cash_flows, start=1)
    )
    terminal_value = cash_flows[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    n = len(cash_flows)
    pv_terminal = terminal_value / (1 + discount_rate) ** n
    return pv_explicit + pv_terminal


def dcf(cash_flows: list[float], discount_rate: float, terminal_growth: float) -> DCFResult:
    """Base-case DCF plus bull/base/bear variants (±100bps discount rate,
    ±50bps terminal growth around the supplied base assumptions)."""
    scenario_deltas: list[tuple[str, float, float]] = [
        ("bull", _BULL_RATE_DELTA, _BULL_GROWTH_DELTA),
        ("base", 0.0, 0.0),
        ("bear", _BEAR_RATE_DELTA, _BEAR_GROWTH_DELTA),
    ]
    scenarios = [
        DCFScenario(
            label=label,  # type: ignore[arg-type]
            discount_rate=discount_rate + rate_delta,
            terminal_growth=terminal_growth + growth_delta,
            present_value=_present_value(
                cash_flows, discount_rate + rate_delta, terminal_growth + growth_delta
            ),
        )
        for label, rate_delta, growth_delta in scenario_deltas
    ]
    return DCFResult(cash_flows=cash_flows, scenarios=scenarios)


def _enterprise_value(f: PeerFinancials) -> float | None:
    if f.total_debt is None or f.cash_and_equivalents is None:
        return None
    return f.price * f.shares_outstanding + f.total_debt - f.cash_and_equivalents


def _multiples(f: PeerFinancials) -> PeerMultiples:
    market_cap = f.price * f.shares_outstanding
    ev = _enterprise_value(f)
    pe = market_cap / f.net_income if f.net_income else None
    ev_to_revenue = ev / f.revenue if ev is not None and f.revenue else None
    ev_to_ebitda = ev / f.ebitda if ev is not None and f.ebitda else None
    return PeerMultiples(
        ticker=f.ticker, pe_ratio=pe, ev_to_revenue=ev_to_revenue, ev_to_ebitda=ev_to_ebitda
    )


def _median_ignoring_none(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


def trailing_free_cash_flows(bundle: FinancialStatementBundle) -> list[float] | None:
    """Last N annual (10-K) periods' operating_cash_flow - capex, oldest
    first — the 'filed cash flows' a trailing DCF discounts as if they were
    the next N years' cash flows (see the Phase 4 plan's Problem/Solution:
    the skill doc specifies a trailing/LTM DCF, not a growth-projection
    model, so no forecasting step is needed here). Mirrors
    ratios.py::compute_trend_bundle's exact annual-period filter. None if
    fewer than 2 usable periods (both fields present) survive."""
    annual = sorted((p for p in bundle.periods if p.form == "10-K"), key=lambda p: p.period_end)
    flows = [
        p.operating_cash_flow - p.capex
        for p in annual
        if p.operating_cash_flow is not None and p.capex is not None
    ]
    return flows if len(flows) >= 2 else None


def build_valuation_assumptions(
    macro_bundles: list[MacroSeriesBundle],
) -> ValuationAssumptions | None:
    """Risk-free rate = the most recent non-None FRED DGS10 observation;
    discount rate = that plus the fixed equity-risk-premium assumption.
    None (a full coverage gap for the whole Valuation section — DCF cannot
    proceed without a discount rate) if no DGS10 bundle is present or every
    one of its points is None (a FRED outage for that series)."""
    dgs10 = next((b for b in macro_bundles if b.series_id == "DGS10"), None)
    if dgs10 is None:
        return None
    sorted_points = sorted(dgs10.points, key=lambda pt: pt.obs_date, reverse=True)
    latest = next((p for p in sorted_points if p.value is not None), None)
    if latest is None or latest.value is None:
        return None
    risk_free_rate = latest.value / 100  # DGS10 is a percentage (e.g. 4.2), not a decimal
    return ValuationAssumptions(
        risk_free_rate=risk_free_rate,
        risk_free_rate_as_of=latest.obs_date,
        equity_risk_premium=_EQUITY_RISK_PREMIUM,
        discount_rate=risk_free_rate + _EQUITY_RISK_PREMIUM,
        terminal_growth=_TERMINAL_GROWTH_ASSUMPTION,
    )


def peer_multiples(target: PeerFinancials, peers: list[PeerFinancials]) -> PeerCompsResult:
    target_multiples = _multiples(target)
    peer_multiples_list = [_multiples(p) for p in peers]
    return PeerCompsResult(
        target=target_multiples,
        peers=peer_multiples_list,
        peer_median_pe=_median_ignoring_none([p.pe_ratio for p in peer_multiples_list]),
        peer_median_ev_to_revenue=_median_ignoring_none(
            [p.ev_to_revenue for p in peer_multiples_list]
        ),
        peer_median_ev_to_ebitda=_median_ignoring_none(
            [p.ev_to_ebitda for p in peer_multiples_list]
        ),
    )
