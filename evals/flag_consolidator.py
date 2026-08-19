"""Eval dataset for the Flag Consolidator.

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.flag_consolidator
Passing bar (see .agents/plans/phase-2-filings-transcript-consolidator.md):
- flags_preserved at 100% across all cases — hard gate (no flag lost,
  none duplicated, none fabricated).
- ExpectedGroupingPresent passes on all 3 cases.
No LLMJudge here: grouping correctness is fully checkable deterministically
and by recall, so a judge would violate CLAUDE.md's evaluator-preference
order ("reach for a judge only when no deterministic/recall check can
substitute").
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from agentic_fundamental_analyst.contracts.consolidation import ConsolidatedFlag
from agentic_fundamental_analyst.contracts.flags import Flag, Severity
from agentic_fundamental_analyst.contracts.sourcing import SourcedFigure, SourcedQuote
from agentic_fundamental_analyst.flags import deduplicate_exact_flags


def _numeric_flag(metric: str, fiscal_year: int, description: str) -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        severity=Severity.MEDIUM,
        description=description,
        source=SourcedFigure(
            value=4.3, source=f"ratios.{metric}", as_of=date(fiscal_year, 12, 31)
        ),
    )


def _quote_flag(metric: str, fiscal_year: int, description: str) -> Flag:
    return Flag(
        metric=metric,
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        severity=Severity.MEDIUM,
        description=description,
        source=SourcedQuote(text="quoted text", source="EDGAR:x", as_of=date(fiscal_year, 12, 31)),
    )


# --- no_overlap_no_merge: three unrelated flags ---
_NO_OVERLAP = [
    _numeric_flag("cash_conversion_ratio", 2023, "Cash conversion weakened in FY2023."),
    _quote_flag("auditor_change", 2024, "Auditor dismissed per the 8-K."),
    _numeric_flag("sloan_accruals", 2022, "Elevated accruals in FY2022."),
]

# --- cross_analyst_capex_merge: same AI-buildout program, two analysts ---
_CAPEX_RATIO = _numeric_flag(
    "capex_to_depreciation_ratio",
    2024,
    "Capex/D&A jumped to 4.3x in FY2024, driven by an AI data-center buildout.",
)
_CAPEX_MDNA = _quote_flag(
    "non_gaap_gap_widening",
    2024,
    "MD&A discloses a significant new AI data-center capital expenditure program in FY2024.",
)
_CAPEX_MERGE = [_CAPEX_RATIO, _CAPEX_MDNA]

# --- duplicate_flags_exact_dedup: two analysts raise the identical (metric, period) ---
_DUP_A = _numeric_flag("capex_to_depreciation_ratio", 2024, "Capex spike, analyst A.")
_DUP_B = _numeric_flag("capex_to_depreciation_ratio", 2024, "Capex spike, analyst B.")
_DUPLICATES = [_DUP_A, _DUP_B]


@dataclass
class FlagConsolidatorGroundingEvaluator(Evaluator[list[Flag], list[ConsolidatedFlag], dict]):
    """Hard gate: the multiset of all Flags across every output
    ConsolidatedFlag must equal exactly deduplicate_exact_flags(inputs) —
    every input flag survives exactly once, none fabricated."""

    def evaluate(
        self, ctx: EvaluatorContext[list[Flag], list[ConsolidatedFlag], dict]
    ) -> dict[str, bool]:
        expected_ids = sorted(id(f) for f in deduplicate_exact_flags(ctx.inputs))
        actual_ids = sorted(id(f) for c in ctx.output for f in c.flags)
        return {"flags_preserved": expected_ids == actual_ids}


@dataclass
class ExpectedGroupingPresent(Evaluator[list[Flag], list[ConsolidatedFlag], dict]):
    """Recall check keyed off metadata['expect_merged'] — a pair of flag
    objects (by identity) that should land in the same ConsolidatedFlag."""

    def evaluate(
        self, ctx: EvaluatorContext[list[Flag], list[ConsolidatedFlag], dict]
    ) -> bool:
        expect_merged = (ctx.metadata or {}).get("expect_merged")
        if not expect_merged:
            return True
        a, b = expect_merged
        for consolidated in ctx.output:
            ids = {id(f) for f in consolidated.flags}
            if id(a) in ids and id(b) in ids:
                return True
        return False


dataset = Dataset(
    name="flag_consolidator",
    cases=[
        Case(name="no_overlap_no_merge", inputs=_NO_OVERLAP, metadata={}),
        Case(
            name="cross_analyst_capex_merge",
            inputs=_CAPEX_MERGE,
            metadata={"expect_merged": (_CAPEX_RATIO, _CAPEX_MDNA)},
        ),
        Case(name="duplicate_flags_exact_dedup", inputs=_DUPLICATES, metadata={}),
    ],
    evaluators=[FlagConsolidatorGroundingEvaluator(), ExpectedGroupingPresent()],
)


if __name__ == "__main__":
    from agentic_fundamental_analyst.agents.flag_consolidator import run_flag_consolidator

    report = dataset.evaluate_sync(run_flag_consolidator)
    report.print(include_input=False, include_output=True, include_durations=True)
