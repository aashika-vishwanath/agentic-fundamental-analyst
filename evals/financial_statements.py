"""Eval dataset for the Financial Statements Analyst.

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.financial_statements
Passing bar (see .agents/plans/phase-1-financial-statements-analyst.md):
- FinancialStatementsGroundingEvaluator's `flags_grounded` at 100% across all cases — hard gate.
- ExpectedFlagsPresent passes on all 6 cases, including the zero-flag clean case.
- LLMJudge summary-quality rubric passes on at least 5/6 (softest bar; never loosen the rubric
  to make a failure disappear — flag it instead).
"""

import re
from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import FINANCIAL_STATEMENTS_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.financial_analyst import FinancialAnalystOutput
from agentic_fundamental_analyst.contracts.financials import FinancialStatementBundle, FiscalPeriod
from agentic_fundamental_analyst.contracts.ratios import RatioTrendBundle
from agentic_fundamental_analyst.ratios import compute_trend_bundle


def _period(
    fiscal_year: int,
    period_end: date,
    revenue: float,
    net_income: float,
    capex: float,
    depreciation_amortization: float,
    accounts_receivable: float,
    inventory: float,
    total_assets: float,
    operating_cash_flow: float,
    cost_of_revenue: float,
    sga_expense: float,
    current_assets: float,
    ppe_gross: float,
    total_debt: float,
) -> FiscalPeriod:
    return FiscalPeriod(
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        form="10-K",
        period_end=period_end,
        revenue=revenue,
        net_income=net_income,
        capex=capex,
        depreciation_amortization=depreciation_amortization,
        accounts_receivable=accounts_receivable,
        inventory=inventory,
        total_assets=total_assets,
        operating_cash_flow=operating_cash_flow,
        cost_of_revenue=cost_of_revenue,
        sga_expense=sga_expense,
        current_assets=current_assets,
        ppe_gross=ppe_gross,
        total_debt=total_debt,
    )


def _bundle(ticker: str, *periods: FiscalPeriod) -> FinancialStatementBundle:
    return FinancialStatementBundle(
        ticker=ticker, cik="0000000001", periods=list(periods), coverage_gaps=[]
    )


# --- clean_financials_no_flags: 3 years, steady/healthy ratios throughout ---
_CLEAN_Y1 = _period(
    2022, date(2022, 12, 31), 1000.0, 100.0, 48.0, 40.0, 110.0, 90.0, 2000.0, 105.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)
_CLEAN_Y2 = _period(
    2023, date(2023, 12, 31), 1060.0, 106.0, 51.0, 42.0, 116.0, 95.0, 2100.0, 111.0,
    636.0, 159.0, 525.0, 735.0, 410.0,
)
_CLEAN_Y3 = _period(
    2024, date(2024, 12, 31), 1124.0, 112.0, 54.0, 44.0, 123.0, 101.0, 2200.0, 117.0,
    674.0, 169.0, 552.0, 772.0, 420.0,
)

# --- receivables_outpacing_revenue: AR +40% vs. revenue +8% in the latest year ---
_RECV_PRIOR = _period(
    2023, date(2023, 12, 31), 1000.0, 100.0, 50.0, 42.0, 100.0, 90.0, 2000.0, 105.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)
_RECV_CURRENT = _period(
    2024, date(2024, 12, 31), 1080.0, 108.0, 52.0, 44.0, 140.0, 95.0, 2100.0, 110.0,
    648.0, 162.0, 525.0, 735.0, 410.0,
)

# --- capex_spike_flagged: capex/D&A jumps from ~1.2x to ~3.2x in the latest year ---
_CAPEX_PRIOR = _period(
    2023, date(2023, 12, 31), 1000.0, 100.0, 50.0, 42.0, 100.0, 90.0, 2000.0, 105.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)
_CAPEX_CURRENT = _period(
    2024, date(2024, 12, 31), 1080.0, 108.0, 140.0, 44.0, 108.0, 95.0, 2100.0, 110.0,
    648.0, 162.0, 525.0, 735.0, 410.0,
)

# --- weak_cash_conversion: CFO/NI drops from 0.95 to 0.35 in the latest year ---
_CCR_PRIOR = _period(
    2023, date(2023, 12, 31), 1000.0, 100.0, 50.0, 42.0, 100.0, 90.0, 2000.0, 95.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)
_CCR_CURRENT = _period(
    2024, date(2024, 12, 31), 1080.0, 115.0, 52.0, 44.0, 108.0, 95.0, 2100.0, 40.0,
    648.0, 162.0, 525.0, 735.0, 410.0,
)

# --- high_beneish_m_score: engineered so M > -1.78 (verified: M ≈ 0.80) ---
_BENEISH_PRIOR = _period(
    2023, date(2023, 12, 31), 1000.0, 100.0, 50.0, 42.0, 82.19, 90.0, 2000.0, 110.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)
_BENEISH_CURRENT = _period(
    2024, date(2024, 12, 31), 1500.0, 150.0, 60.0, 44.0, 369.86, 95.0, 2000.0, -50.0,
    1200.0, 225.0, 467.0, 733.0, 400.0,
)

# --- single_period_coverage_gap: one 10-K only (e.g. a recent IPO) ---
_SINGLE_PERIOD = _period(
    2024, date(2024, 12, 31), 1000.0, 100.0, 50.0, 42.0, 100.0, 90.0, 2000.0, 105.0,
    600.0, 150.0, 500.0, 700.0, 400.0,
)


# --- deterministic evaluators (preference order: deterministic > recall > judge) ---

_NUMBER_RE = re.compile(r"-?\d+\.?\d*")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def _extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        token = match.group()
        if _YEAR_RE.match(token):
            continue
        try:
            numbers.append(float(token))
        except ValueError:
            continue
    return numbers


def _known_numbers(trend: RatioTrendBundle) -> set[float]:
    known: set[float] = set()
    for period in trend.periods:
        raw_fields = (
            period.revenue,
            period.net_income,
            period.capex,
            period.depreciation_amortization,
        )
        for raw in raw_fields:
            if raw is not None:
                known.add(round(raw, 4))
        ratios = (
            period.days_sales_outstanding,
            period.receivables_growth_vs_revenue_growth,
            period.inventory_growth_vs_cogs_growth,
            period.sloan_accruals,
            period.cash_conversion_ratio,
            period.capex_to_depreciation_ratio,
            period.days_inventory_outstanding,
            period.cash_conversion_cycle,
            period.beneish_m_score,
        )
        for ratio in ratios:
            if ratio.value is not None:
                v = ratio.value
                # Common derived transforms a narrative might apply: raw ratio,
                # expressed as a percent, or rounded to a whole "N days"/"N%".
                known.update({round(v, 4), round(v * 100, 4), round(v), round(v * 100)})
    return known


def _is_grounded(x: float, known: set[float]) -> bool:
    tolerance = max(0.5, 0.01 * abs(x))
    return any(abs(x - k) <= tolerance for k in known)


def _summary_numeric_grounding_ratio(summary: str, trend: RatioTrendBundle) -> float:
    """Best-effort: fraction of numbers appearing in free text that are traceable
    to the input. Can under-catch (a correctly-derived but rephrased number);
    should not over-flag genuinely grounded content given the generous tolerance.
    Informational, not the hard gate — see module docstring."""
    numbers = _extract_numbers(summary)
    if not numbers:
        return 1.0
    known = _known_numbers(trend)
    grounded = sum(1 for x in numbers if _is_grounded(x, known))
    return grounded / len(numbers)


@dataclass
class FinancialStatementsGroundingEvaluator(
    Evaluator[FinancialStatementBundle, FinancialAnalystOutput, dict]
):
    """The hard deterministic gate: every Flag.source.value must trace exactly
    to the RatioTrendBundle recomputed from the case's own input — this also
    doubles as a regression check on _ground_candidates itself, not just on
    agent behavior."""

    def evaluate(
        self, ctx: EvaluatorContext[FinancialStatementBundle, FinancialAnalystOutput, dict]
    ) -> dict[str, bool | float]:
        trend = compute_trend_bundle(ctx.inputs)
        by_period = {(p.fiscal_year, p.fiscal_period): p for p in trend.periods}
        flags_grounded = True
        for flag in ctx.output.flags:
            period = by_period.get((flag.fiscal_year, flag.fiscal_period))
            result = getattr(period, flag.metric, None) if period is not None else None
            if period is None or result is None or result.value is None:
                flags_grounded = False
                continue
            if abs(flag.source.value - result.value) > 1e-6:
                flags_grounded = False
        return {
            "flags_grounded": flags_grounded,
            "summary_numeric_grounding_ratio": _summary_numeric_grounding_ratio(
                ctx.output.summary, trend
            ),
        }


@dataclass
class ExpectedFlagsPresent(Evaluator[FinancialStatementBundle, FinancialAnalystOutput, dict]):
    """Recall check keyed off each Case's metadata['expected_flag_metrics'].
    An empty expected set means the clean-case assertion: zero flags raised."""

    def evaluate(
        self, ctx: EvaluatorContext[FinancialStatementBundle, FinancialAnalystOutput, dict]
    ) -> bool:
        expected = set((ctx.metadata or {}).get("expected_flag_metrics", ()))
        actual = {flag.metric for flag in ctx.output.flags}
        if not expected:
            return actual == set()
        return expected.issubset(actual)


_SUMMARY_QUALITY_RUBRIC = (
    "The summary is a specific, numeric interpretation of this company's own "
    "financial trend, not generic language that could describe any company in "
    "its sector. "
    "Each entry in coverage_gaps is scoped to one exact fiscal year, e.g. "
    "'beneish_m_score:2023FY' means only the 2023 Beneish score is unavailable "
    "-- the same metric in a different fiscal year NOT listed in coverage_gaps "
    "is a real, computed value and may be freely and correctly characterized as "
    "healthy or concerning. The summary fails this rubric only if it "
    "characterizes a metric as healthy or concerning for the *specific fiscal "
    "year* coverage_gaps marks as unavailable for that metric -- describing a "
    "different, non-gap-marked fiscal year for that same metric name is not a "
    "violation."
)

dataset = Dataset(
    name="financial_statements",
    cases=[
        Case(
            name="clean_financials_no_flags",
            inputs=_bundle("CLEAN", _CLEAN_Y1, _CLEAN_Y2, _CLEAN_Y3),
            metadata={"expected_flag_metrics": []},
        ),
        Case(
            name="receivables_outpacing_revenue",
            inputs=_bundle("RECV", _RECV_PRIOR, _RECV_CURRENT),
            metadata={"expected_flag_metrics": ["receivables_growth_vs_revenue_growth"]},
        ),
        Case(
            name="capex_spike_flagged",
            inputs=_bundle("CAPEX", _CAPEX_PRIOR, _CAPEX_CURRENT),
            metadata={"expected_flag_metrics": ["capex_to_depreciation_ratio"]},
        ),
        Case(
            name="weak_cash_conversion",
            inputs=_bundle("CCR", _CCR_PRIOR, _CCR_CURRENT),
            metadata={"expected_flag_metrics": ["cash_conversion_ratio"]},
        ),
        Case(
            name="high_beneish_m_score",
            inputs=_bundle("BENEISH", _BENEISH_PRIOR, _BENEISH_CURRENT),
            metadata={"expected_flag_metrics": ["beneish_m_score"]},
        ),
        Case(
            name="single_period_coverage_gap",
            inputs=_bundle("IPO", _SINGLE_PERIOD),
            metadata={"expected_flag_metrics": []},
        ),
    ],
    evaluators=[
        FinancialStatementsGroundingEvaluator(),
        ExpectedFlagsPresent(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=FINANCIAL_STATEMENTS_ANALYST_MODEL),
    ],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.financial_statements import (
        run_financial_statements_analyst,
    )

    report = dataset.evaluate_sync(run_financial_statements_analyst)
    report.print(include_input=False, include_output=True, include_durations=True)
