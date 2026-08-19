"""Deterministic valuation math — DCF and self-built peer multiples.
Arithmetic on disclosed/typed inputs only; interpreting the result is the
Valuation Interpreter agent's job (Phase 4), not this module's (PRD §4).
"""

import statistics

from agentic_fundamental_analyst.contracts.valuation import (
    DCFResult,
    DCFScenario,
    PeerCompsResult,
    PeerFinancials,
    PeerMultiples,
)

_BULL_RATE_DELTA = -0.01
_BULL_GROWTH_DELTA = 0.005
_BEAR_RATE_DELTA = 0.01
_BEAR_GROWTH_DELTA = -0.005


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
