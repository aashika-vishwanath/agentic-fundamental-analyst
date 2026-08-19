# Valuation Math — Implementation Reference

Status: built, Phase 0 complete. Pure arithmetic on typed/disclosed inputs
— interpreting the output (what it means for the thesis) is the Valuation
Interpreter agent's job (Phase 4), not this module's (PRD §4).

## DCF (`valuation.py::dcf`)

`dcf(cash_flows: list[float], discount_rate: float, terminal_growth: float) -> DCFResult`

Base case is whatever `discount_rate`/`terminal_growth` the caller supplies
(sourcing those — e.g. FRED `DGS10` as the risk-free-rate component, plus a
disclosed equity-risk-premium assumption — is the caller's job, not this
function's; it takes plain floats, not a FRED series). Bull/bear scenarios
are generated automatically: ±100bps on the discount rate, ±50bps on
terminal growth, around the supplied base case. Standard two-stage model:
explicit-period cash flows discounted year by year, plus a Gordon-growth
terminal value discounted back from the final projection year.

`present_value=None` (not a fabricated number) whenever `discount_rate <=
terminal_growth` for a given scenario — an undefined/negative terminal
value, not a real scenario to report.

## Peer multiples (`valuation.py::peer_multiples`)

`peer_multiples(target: PeerFinancials, peers: list[PeerFinancials]) -> PeerCompsResult`

Computes P/E, EV/Revenue, EV/EBITDA per company (`PeerFinancials` is a
single flat snapshot: price, shares outstanding, revenue, net income,
EBITDA, total debt, cash — the caller is responsible for peer selection,
i.e. building the SIC-matched peer set via `EdgarClient`/`excluded_sic.py`
before calling this). Peer medians use `statistics.median` and silently
exclude `None`s from the calculation — a peer missing one input (e.g. no
EBITDA tag resolved) never zeroes out or skews the peer group's median for
that metric.

## Golden tests

`tests/unit/test_valuation.py` — a synthetic 3-year cash-flow scenario for
DCF (independently re-derived in the test via a second, separately-written
PV loop, not by calling back into `valuation.py`'s own helper), and a
3-company synthetic peer set (including one peer with a missing field, to
prove `None` propagates rather than becoming a 0 in the median) for peer
multiples.
