"""The Financial Statements Analyst — the first LLM agent in the pipeline.

Interprets deterministically-computed earnings-quality ratio trends
(checklist items #1-7 in the investment-memo-writing skill) and raises Flags
where warranted, plus a short narrative summary for the memo's Financial
Analysis section. See .agents/plans/phase-1-financial-statements-analyst.md
for the full design rationale.

Grounding is enforced structurally, not just checked after the fact: the
agent's own output type (FinancialAnalystAgentOutput / FlagCandidate) never
carries a numeric value at all. It names *what* it thinks is flag-worthy —
a (metric, fiscal_year, fiscal_period) triple — and _ground_candidates below
looks up the real RatioResult.value deterministically, building the final
Flag's SourcedFigure from code, never from the model. Any candidate whose
metric/period doesn't resolve to a real value is dropped, not trusted.
"""

import logfire
from pydantic_ai import Agent

# Import order within this line matters: config loads .env (so
# ANTHROPIC_API_KEY/LOGFIRE_TOKEN are in os.environ) before observability
# configures Logfire.
from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.models import FINANCIAL_STATEMENTS_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.financial_analyst import (
    FinancialAnalystAgentOutput,
    FinancialAnalystOutput,
    FlagCandidate,
)
from agentic_fundamental_analyst.contracts.financials import CoverageGap, FinancialStatementBundle
from agentic_fundamental_analyst.contracts.flags import Flag
from agentic_fundamental_analyst.contracts.ratios import PeriodRatios, RatioTrendBundle
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure
from agentic_fundamental_analyst.ratios import compute_trend_bundle

_INSTRUCTIONS = """\
You are the Financial Statements Analyst for a fundamental-equity research system.
You receive a RatioTrendBundle: a company's earnings-quality ratios computed
deterministically, one entry per annual (10-K) fiscal period, oldest first. Every
number in it is already correct — never restate a ratio's value from memory, and
never invent a fiscal year, fiscal period, or ratio name that is not present in
the bundle.

Task:
1. Write a 2-4 sentence `summary` of the company's financial trend across the
   supplied periods -- margins, cash conversion, leverage direction -- specific
   to this company's actual numbers, not generic commentary that could describe
   any company in its sector.
2. For each period, decide whether any of these seven checklist ratios warrants a
   red flag. These thresholds are a starting point for judgment, not a mechanical
   trigger -- always read a number in the context of the trend across periods:
   - days_sales_outstanding: multi-period uptrend
   - receivables_growth_vs_revenue_growth: gap > ~10 percentage points, persistent
   - inventory_growth_vs_cogs_growth: gap > ~10 percentage points, persistent
   - sloan_accruals: large and rising positive value
   - cash_conversion_ratio: persistently below ~0.8, or trending down
   - capex_to_depreciation_ratio: consistently > ~2x. You have no filing text in
     this input, so you cannot tell whether a spike is disclosed growth capex --
     treat any sustained spike as a candidate flag; a later stage investigates it
     with outside context.
   - beneish_m_score: above the conventional -1.78 threshold
   A period where a ratio's value is null and it carries a reason is a coverage
   gap, not a flag and not evidence of anything -- never treat a missing ratio as
   either bullish or bearish.
3. Only raise a flag for a (metric, fiscal_year, fiscal_period) combination that
   appears in the bundle with a non-null value for that metric. Do not raise a
   flag for a number you cannot see.
4. Raising zero flags is a valid, expected outcome for a clean set of financials --
   do not manufacture a flag to seem thorough.
"""

financial_statements_analyst = Agent(
    FINANCIAL_STATEMENTS_ANALYST_MODEL,
    name="financial_statements_analyst",
    output_type=FinancialAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)

_FLAGGABLE_METRICS: tuple[str, ...] = (
    "days_sales_outstanding",
    "receivables_growth_vs_revenue_growth",
    "inventory_growth_vs_cogs_growth",
    "sloan_accruals",
    "cash_conversion_ratio",
    "capex_to_depreciation_ratio",
    "beneish_m_score",
)


def _ground_candidates(
    trend: RatioTrendBundle, candidates: list[FlagCandidate]
) -> tuple[list[Flag], list[str]]:
    by_period: dict[tuple[int, str], PeriodRatios] = {
        (p.fiscal_year, p.fiscal_period): p for p in trend.periods
    }
    flags: list[Flag] = []
    dropped: list[str] = []
    for candidate in candidates:
        period = by_period.get((candidate.fiscal_year, candidate.fiscal_period))
        result = getattr(period, candidate.metric, None) if period is not None else None
        if period is None or result is None or result.value is None:
            dropped.append(
                f"{candidate.metric} {candidate.fiscal_year}{candidate.fiscal_period}: "
                "no matching value in RatioTrendBundle"
            )
            continue
        flags.append(
            Flag(
                metric=candidate.metric,
                fiscal_year=candidate.fiscal_year,
                fiscal_period=candidate.fiscal_period,
                severity=candidate.severity,
                description=candidate.description,
                source=SourcedFigure(
                    value=result.value,
                    source=(
                        f"ratios.{candidate.metric}:{trend.ticker}:"
                        f"{candidate.fiscal_year}{candidate.fiscal_period}"
                    ),
                    as_of=period.period_end,
                ),
            )
        )
    return flags, dropped


def _ratio_unavailable_gaps(trend: RatioTrendBundle) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []
    for period in trend.periods:
        for metric in _FLAGGABLE_METRICS:
            result = getattr(period, metric)
            if result.value is None:
                gaps.append(
                    CoverageGap(
                        field=f"{metric}:{period.fiscal_year}{period.fiscal_period}",
                        reason=result.reason or "unavailable",
                    )
                )
    return gaps


async def run_financial_statements_analyst(
    bundle: FinancialStatementBundle,
) -> FinancialAnalystOutput:
    trend = compute_trend_bundle(bundle)
    with logfire.span(
        "financial_statements_analyst_stage", ticker=bundle.ticker
    ) as span:
        result = await financial_statements_analyst.run(trend.model_dump_json(indent=2))
        agent_output = result.output
        flags, dropped = _ground_candidates(trend, agent_output.flag_candidates)
        span.set_attribute("flag_count", len(flags))
        span.set_attribute("dropped_candidate_count", len(dropped))
    return FinancialAnalystOutput(
        ticker=bundle.ticker,
        summary=agent_output.summary,
        flags=flags,
        coverage_gaps=[*bundle.coverage_gaps, *_ratio_unavailable_gaps(trend)],
        dropped_candidates=dropped,
    )
