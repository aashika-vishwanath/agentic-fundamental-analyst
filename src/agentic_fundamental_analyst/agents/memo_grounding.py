"""Per-section numeric grounding for the Synthesizer (Phase 5). Builds on
agents/numeric_grounding.py wholesale -- no new regex, no new tolerance
logic -- the only new work is (a) harvesting a much larger "known numbers"
universe from every upstream typed field a MemoSynthesisInput carries
(including raw filing prose, where earlier phases never needed to look), and
(b) a PER-SECTION gate instead of Phase 4's per-agent-output gate: one bad
number replaces only that section's content, not the whole memo.

Two-part hard gate per section, both checked against the same known-numbers
universe: every number appearing in `content` must ground, AND every
`cited_figures` value must ground too -- the second check is what actually
enforces Section 10's traceability promise (a fabricated SourcedFigure with
an invented value and a plausible-looking fake source string would pass a
content-only check).
"""

from itertools import combinations

from agentic_fundamental_analyst.agents.numeric_grounding import extract_numbers, is_grounded
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.memo import MemoSection, MemoSectionAgentOutput
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.contracts.synthesis import MemoSynthesisInput

_FALLBACK_CONTENT = (
    "Narrative generation did not pass the numeric-grounding check for this section; "
    "see coverage_gaps."
)


def known_numbers_from_synthesis_input(input: MemoSynthesisInput) -> set[float]:
    known: set[float] = set()

    # Raw filing prose -- the one source of legitimately-citable numbers no
    # earlier phase needed to harvest this way (debt maturities, contract
    # amounts, employee counts, etc. disclosed only in narrative text).
    filing_texts = [
        input.filings.item_1_business,
        input.filings.item_1a_risk_factors,
        input.filings.item_7_mdna,
        input.filings.item_9a_controls,
        *input.filings.eightk_item_bodies.values(),
    ]
    for text in filing_texts:
        if text:
            known.update(extract_numbers(text))

    # RatioTrendBundle -- computed ratios plus the raw values carried through.
    for period in input.ratio_trend.periods:
        for result in (
            period.days_sales_outstanding,
            period.receivables_growth_vs_revenue_growth,
            period.inventory_growth_vs_cogs_growth,
            period.sloan_accruals,
            period.cash_conversion_ratio,
            period.capex_to_depreciation_ratio,
            period.days_inventory_outstanding,
            period.beneish_m_score,
        ):
            if result.value is not None:
                known.add(round(result.value, 4))
        for raw in (
            period.revenue,
            period.net_income,
            period.capex,
            period.depreciation_amortization,
        ):
            if raw is not None:
                known.add(round(raw, 4))

    # Raw FinancialStatementBundle -- fields not carried through RatioTrendBundle.
    for period in input.financials.periods:
        for raw in (
            period.revenue,
            period.net_income,
            period.capex,
            period.depreciation_amortization,
            period.accounts_receivable,
            period.inventory,
            period.total_assets,
            period.operating_cash_flow,
            period.cost_of_revenue,
            period.sga_expense,
            period.current_assets,
            period.ppe_gross,
            period.total_debt,
        ):
            if raw is not None:
                known.add(round(raw, 4))

    known.add(round(input.latest_price, 4))

    for bundle in input.macro_bundles:
        for point in bundle.points:
            if point.value is not None:
                known.add(round(point.value, 4))

    # ValuationResult -- assumptions, DCF scenarios, comps.
    a = input.valuation_result.assumptions
    for value in (a.risk_free_rate, a.equity_risk_premium, a.discount_rate, a.terminal_growth):
        known.add(round(value, 4))
        known.add(round(value * 100, 4))
    if input.valuation_result.dcf is not None:
        for scenario in input.valuation_result.dcf.scenarios:
            known.add(round(scenario.discount_rate, 4))
            known.add(round(scenario.discount_rate * 100, 4))
            known.add(round(scenario.terminal_growth, 4))
            known.add(round(scenario.terminal_growth * 100, 4))
            if scenario.present_value is not None:
                known.add(round(scenario.present_value, 4))
    if input.valuation_result.comps is not None:
        comps = input.valuation_result.comps
        for pm in (comps.target, *comps.peers):
            for value in (pm.pe_ratio, pm.ev_to_revenue, pm.ev_to_ebitda):
                if value is not None:
                    known.add(round(value, 4))
        for value in (
            comps.peer_median_pe,
            comps.peer_median_ev_to_revenue,
            comps.peer_median_ev_to_ebitda,
        ):
            if value is not None:
                known.add(round(value, 4))

    # Flags, investigations, and the three Phase 4 summaries -- numbers
    # embedded in prose the model may legitimately re-cite.
    for cf in input.consolidated_flags:
        known.update(extract_numbers(cf.summary))
        for f in cf.flags:
            known.update(extract_numbers(f.description))
            if isinstance(f.source, SourcedFigure):
                known.add(round(f.source.value, 4))
    for v in input.investigations:
        known.update(extract_numbers(v.hypothesis))
        known.update(extract_numbers(v.reasoning))
        for e in v.evidence:
            known.update(extract_numbers(e.claim))

    for text in (
        input.financial_analyst_summary,
        input.filings_analyst_summary,
        input.transcript_analyst_summary,
        input.sector_summary,
        input.macro_summary,
        input.valuation_summary,
    ):
        if text:
            known.update(extract_numbers(text))

    for gap in input.coverage_gaps:
        known.update(extract_numbers(gap.reason))

    return known


# A legitimate narrative comparison ("22% discount to peer median", "40%
# below DCF value") always compares two numbers of roughly the same kind and
# magnitude -- never a raw dollar figure against an unrelated tiny ratio.
# Found live in this phase's own test suite (not by a live model run): a real
# revenue figure (~2M) divided by a real but unrelated small ratio (~0.02)
# produced a spurious ~99M "known" combination that fell within
# numeric_grounding's *relative* 1% tolerance (huge in absolute terms for a
# number that size) of a deliberately fabricated ~1e8 citation, wrongly
# grounding it. agents/numeric_grounding.py::expand_known_numbers's
# unrestricted pairwise cross-product is safe for Phase 4's small,
# homogeneous, comparison-oriented known sets (peer multiples, macro rates)
# but breaks down over Phase 5's much larger, heterogeneous universe -- so
# this module keeps its own bounded expansion rather than reusing that
# function, without touching Phase 4's already-passing behavior.
_MAX_RATIO_FOR_COMPARISON = 100


def _expand_known_numbers(known_raw: set[float]) -> set[float]:
    known: set[float] = set()
    for v in known_raw:
        known.update({round(v, 4), round(v * 100, 4), round(v)})
    for a, b in combinations(known_raw, 2):
        lo, hi = sorted((abs(a), abs(b)))
        if lo == 0 or hi / lo > _MAX_RATIO_FOR_COMPARISON:
            continue
        if b:
            pct = (a - b) / b * 100
            known.add(round(pct, 4))
            known.add(round(abs(pct), 4))
            known.add(round(a / b, 4))
        if a:
            pct2 = (b - a) / a * 100
            known.add(round(pct2, 4))
            known.add(round(abs(pct2), 4))
            known.add(round(b / a, 4))
    return known | known_raw


def section_is_grounded(section: MemoSectionAgentOutput, expanded_known: set[float]) -> bool:
    content_numbers = extract_numbers(section.content)
    if not all(is_grounded(x, expanded_known) for x in content_numbers):
        return False
    cited_values = [round(f.value, 4) for f in section.cited_figures]
    return all(is_grounded(v, expanded_known) for v in cited_values)


def apply_grounding_gate(
    sections: list[MemoSectionAgentOutput], known_raw: set[float]
) -> tuple[list[MemoSection], list[CoverageGap]]:
    """Per-section fallback -- one ungrounded section never costs the other
    nine. `known_raw` is expanded (percent-diff/ratio transforms) exactly
    once per call, shared across every section's check."""
    expanded = _expand_known_numbers(known_raw)
    grounded_sections: list[MemoSection] = []
    gaps: list[CoverageGap] = []
    for s in sections:
        if section_is_grounded(s, expanded):
            grounded_sections.append(MemoSection(**s.model_dump()))
        else:
            grounded_sections.append(
                MemoSection(
                    title=s.title, content=_FALLBACK_CONTENT, cited_figures=[], cited_quotes=[]
                )
            )
            gaps.append(
                CoverageGap(field=f"section:{s.title}", reason="numeric_grounding_check_failed")
            )
    return grounded_sections, gaps
