"""Eval dataset for the Filings Analyst.

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.filings
Passing bar (see .agents/plans/phase-2-filings-transcript-consolidator.md):
- flags_grounded at 100% across all cases — hard gate.
- ExpectedFlagsPresent passes on all 6 cases, including the zero-flag clean case.
- LLMJudge summary-quality rubric passes on at least 5/6 (softest bar; never
  loosen the rubric to make a failure disappear — flag it instead).
"""

from dataclasses import dataclass
from datetime import date

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import FILINGS_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.filings import EightKItemSource, FilingSections
from agentic_fundamental_analyst.contracts.filings_analyst import FilingsAnalystOutput
from agentic_fundamental_analyst.contracts.flags import Flag
from evals.grounding import flags_are_quote_grounded


def _sections(
    *,
    item_1_business: str = (
        "Meridian Audio Corporation designs and sells premium wireless headphones "
        "and home-audio speakers under the Meridian and Solstice brands, distributed "
        "through approximately 1,200 retail partners across North America and Europe."
    ),
    item_1a_risk_factors: str = (
        "We depend on continued relationships with our largest retail partners, who "
        "together accounted for approximately 40% of net revenue in fiscal 2023. We "
        "also rely on a single contract manufacturer in Vietnam to produce our "
        "Solstice speaker line, and any disruption at that facility could delay "
        "shipments during our peak fourth-quarter selling season."
    ),
    item_7_mdna: str = (
        "Net revenue grew 9% year over year to $412 million, driven primarily by "
        "strong demand for the Solstice speaker line following its October 2023 "
        "launch. Gross margin was 38.2%, consistent with 38.0% in the prior year."
    ),
    item_9a_controls: str = (
        "Based on this evaluation, our Chief Executive Officer and Chief Financial "
        "Officer concluded that our disclosure controls and procedures were "
        "effective as of the period end."
    ),
    eightk_item_bodies: dict[str, str] | None = None,
    eightk_item_sources: dict[str, EightKItemSource] | None = None,
) -> FilingSections:
    return FilingSections(
        accession_number="0001234567-24-000010",
        filed_date=date(2024, 2, 15),
        period_of_report=date(2023, 12, 31),
        item_1_business=item_1_business,
        item_1a_risk_factors=item_1a_risk_factors,
        item_7_mdna=item_7_mdna,
        item_9a_controls=item_9a_controls,
        eightk_item_bodies=eightk_item_bodies or {},
        eightk_item_sources=eightk_item_sources or {},
        coverage_gaps=[],
    )


CLEAN = _sections()

AUDITOR_CHANGE = _sections(
    eightk_item_bodies={
        "4.01": (
            "On March 3, 2024, the Audit Committee of the Board of Directors dismissed "
            "Example & Co LLP as the Company's independent registered public accounting "
            "firm, effective immediately. The Audit Committee has commenced a process to "
            "select a new independent registered public accounting firm."
        )
    },
    eightk_item_sources={
        "4.01": EightKItemSource(
            accession_number="0001234567-24-000011", filed_date=date(2024, 3, 3)
        )
    },
)

OFFICER_TURNOVER = _sections(
    eightk_item_bodies={
        "5.02": (
            "On April 10, 2024, Jordan Rivera departed as the Company's Chief "
            "Financial Officer, effective immediately. The Company has not yet "
            "identified a successor; the Chief Executive Officer will serve as "
            "interim principal financial officer in the meantime. Ms. Rivera's "
            "departure follows the Company's April 8, 2024 announcement that "
            "first-quarter results would fall short of previously issued guidance."
        )
    },
    eightk_item_sources={
        "5.02": EightKItemSource(
            accession_number="0001234567-24-000012", filed_date=date(2024, 4, 10)
        )
    },
)

MATERIAL_WEAKNESS = _sections(
    item_9a_controls=(
        "Based on this evaluation, management concluded that our disclosure controls "
        "and procedures were not effective as of December 31, 2023. In connection with "
        "the preparation of our financial statements, we identified a material "
        "weakness in our internal control over financial reporting related to the "
        "review of complex revenue recognition arrangements."
    )
)

GOING_CONCERN = _sections(
    item_7_mdna=(
        "Revenue declined 22% year over year. Our recurring losses from operations "
        "and negative cash flows raise substantial doubt about our ability to "
        "continue as a going concern for at least the next twelve months."
    )
)

RESTATEMENT = _sections(
    eightk_item_bodies={
        "4.02": (
            "On May 6, 2024, the Audit Committee concluded that the Company's "
            "previously issued financial statements for fiscal year 2022 should no "
            "longer be relied upon due to an error in the recognition of certain "
            "multi-year service contracts."
        )
    },
    eightk_item_sources={
        "4.02": EightKItemSource(
            accession_number="0001234567-24-000013", filed_date=date(2024, 5, 6)
        )
    },
)


def _source_text_for(sections: FilingSections, flag: Flag) -> str | None:
    """Mirrors agents/filings.py's own section-routing logic — the eval
    dataset independently re-derives which text a flag's source claims,
    from the flag's SourcedQuote.source string, so the check doesn't just
    trust the agent module's own grounding function was applied correctly."""
    source = flag.source.source  # "EDGAR:<accession>[:8K:<item>|:<section>]"
    parts = source.split(":")
    if len(parts) >= 4 and parts[2] == "8K":
        return sections.eightk_item_bodies.get(parts[3])
    if len(parts) >= 3:
        return getattr(sections, parts[2], None)
    return None


@dataclass
class FilingsGroundingEvaluator(Evaluator[FilingSections, FilingsAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[FilingSections, FilingsAnalystOutput, dict]
    ) -> dict[str, bool]:
        grounded = flags_are_quote_grounded(
            ctx.output.flags, lambda flag: _source_text_for(ctx.inputs, flag)
        )
        return {"flags_grounded": grounded}


@dataclass
class ExpectedFlagsPresent(Evaluator[FilingSections, FilingsAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[FilingSections, FilingsAnalystOutput, dict]
    ) -> bool:
        expected = set((ctx.metadata or {}).get("expected_flag_metrics", ()))
        actual = {flag.metric for flag in ctx.output.flags}
        if not expected:
            return actual == set()
        return expected.issubset(actual)


_SUMMARY_QUALITY_RUBRIC = (
    "The summary is a specific interpretation of what THIS filing actually "
    "discloses, citing real language/topics from the input sections, not "
    "generic boilerplate that could describe any company's filing. It does "
    "not claim a checklist signal is present unless the filing text genuinely "
    "supports it."
)

dataset = Dataset(
    name="filings",
    cases=[
        Case(
            name="clean_filing_no_flags",
            inputs=CLEAN,
            metadata={"expected_flag_metrics": []},
        ),
        Case(
            name="auditor_change_flagged",
            inputs=AUDITOR_CHANGE,
            metadata={"expected_flag_metrics": ["auditor_change"]},
        ),
        Case(
            name="officer_turnover_flagged",
            inputs=OFFICER_TURNOVER,
            metadata={"expected_flag_metrics": ["officer_turnover"]},
        ),
        Case(
            name="material_weakness_flagged",
            inputs=MATERIAL_WEAKNESS,
            metadata={"expected_flag_metrics": ["material_weakness"]},
        ),
        Case(
            name="going_concern_flagged",
            inputs=GOING_CONCERN,
            metadata={"expected_flag_metrics": ["going_concern_language"]},
        ),
        Case(
            name="restatement_flagged",
            inputs=RESTATEMENT,
            metadata={"expected_flag_metrics": ["restatement"]},
        ),
    ],
    evaluators=[
        FilingsGroundingEvaluator(),
        ExpectedFlagsPresent(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=FILINGS_ANALYST_MODEL),
    ],
)


if __name__ == "__main__":
    from functools import partial

    from agentic_fundamental_analyst.agents.filings import run_filings_analyst

    report = dataset.evaluate_sync(partial(run_filings_analyst, "TEST"))
    report.print(include_input=False, include_output=True, include_durations=True)
