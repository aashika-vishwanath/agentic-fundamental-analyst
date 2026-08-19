"""Eval dataset for the Transcript Analyst.

Run with: ANTHROPIC_API_KEY=<key> uv run python -m evals.transcripts
Passing bar (see .agents/plans/phase-2-filings-transcript-consolidator.md):
- flags_grounded at 100% across all cases — hard gate.
- ExpectedFlagsPresent passes on all 3 cases.
- LLMJudge summary-quality rubric passes on at least 3/3 (softest bar; never
  loosen the rubric to make a failure disappear — flag it instead).

transcript_unavailable_gap costs zero tokens (the model is never invoked for
a None input) — this is PRD §12's explicitly-named exit-validation case.
"""

from dataclasses import dataclass
from datetime import date
from functools import partial

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext, LLMJudge

from agentic_fundamental_analyst.agents.models import TRANSCRIPT_ANALYST_MODEL
from agentic_fundamental_analyst.agents.transcript import run_transcript_analyst
from agentic_fundamental_analyst.contracts.transcript_analyst import TranscriptAnalystOutput
from agentic_fundamental_analyst.contracts.transcripts import TranscriptInput
from evals.grounding import flags_are_quote_grounded

CLEAN_TRANSCRIPT = TranscriptInput(
    accession_number="0001234567-24-000020",
    filed_date=date(2024, 4, 25),
    exhibit_document="ex991q124earningscalltrans.htm",
    text=(
        "Operator\nWelcome to the first-quarter earnings call.\n"
        "Analyst\nCan you walk us through the gross margin improvement this quarter?\n"
        "CFO\nSure. Gross margin improved 140 basis points to 42.3%, driven primarily "
        "by lower input costs and favorable product mix. We expect a similar cadence "
        "next quarter given our current cost outlook.\n"
        "Analyst\nAnd how should we think about full-year revenue growth?\n"
        "CEO\nWe are reiterating our full-year guidance of 8% to 10% revenue growth, "
        "consistent with what we said last quarter."
    ),
)

EVASIVE_TRANSCRIPT = TranscriptInput(
    accession_number="0001234567-24-000021",
    filed_date=date(2024, 7, 25),
    exhibit_document="ex991q224earningscalltrans.htm",
    text=(
        "Operator\nWelcome to the second-quarter earnings call.\n"
        "Analyst\nCan you tell us the exact gross margin number for the quarter and "
        "whether it came in above or below your internal plan?\n"
        "CFO\nWe're not going to get into that level of granularity on this call, but "
        "directionally we feel good about where things are headed.\n"
        "Analyst\nYou previously guided to 8% to 10% full-year revenue growth. Is that "
        "still the case?\n"
        "CEO\nWe're going to hold off on reiterating a specific number today and revisit "
        "that with you next quarter."
    ),
)


TranscriptCaseInput = TranscriptInput | None


def _source_text_for(transcript: TranscriptCaseInput, flag: object) -> str | None:
    return transcript.text if transcript is not None else None


@dataclass
class TranscriptGroundingEvaluator(Evaluator[TranscriptCaseInput, TranscriptAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[TranscriptCaseInput, TranscriptAnalystOutput, dict]
    ) -> dict[str, bool]:
        grounded = flags_are_quote_grounded(
            ctx.output.flags, lambda flag: _source_text_for(ctx.inputs, flag)
        )
        return {"flags_grounded": grounded}


@dataclass
class ExpectedFlagsPresent(Evaluator[TranscriptCaseInput, TranscriptAnalystOutput, dict]):
    def evaluate(
        self, ctx: EvaluatorContext[TranscriptCaseInput, TranscriptAnalystOutput, dict]
    ) -> bool:
        expected = set((ctx.metadata or {}).get("expected_flag_metrics", ()))
        actual = {flag.metric for flag in ctx.output.flags}
        if not expected:
            return actual == set()
        return expected.issubset(actual)


@dataclass
class UnavailableCaseCorrect(Evaluator[TranscriptCaseInput, TranscriptAnalystOutput, dict]):
    """Deterministic check specific to the None-input case: summary must be
    None, zero flags, and exactly the expected coverage gap — never a judge
    call for this one, it's fully mechanical."""

    def evaluate(
        self, ctx: EvaluatorContext[TranscriptCaseInput, TranscriptAnalystOutput, dict]
    ) -> bool:
        if ctx.inputs is not None:
            return True  # not applicable to the other cases
        expected_reason = "no_transcript_exhibit_found_in_lookback_window"
        return (
            ctx.output.summary is None
            and ctx.output.flags == []
            and len(ctx.output.coverage_gaps) == 1
            and ctx.output.coverage_gaps[0].reason == expected_reason
        )


_SUMMARY_QUALITY_RUBRIC = (
    "The summary describes what management actually said on THIS call, "
    "citing real topics/tone from the transcript, not generic earnings-call "
    "boilerplate. If summary is null, this case is not applicable and passes "
    "automatically."
)

_cases: list[Case[TranscriptCaseInput, TranscriptAnalystOutput, dict]] = [
    Case(
        name="transcript_unavailable_gap",
        inputs=None,
        metadata={"expected_flag_metrics": []},
    ),
    Case(
        name="clean_transcript_no_flags",
        inputs=CLEAN_TRANSCRIPT,
        metadata={"expected_flag_metrics": []},
    ),
    Case(
        name="evasive_guidance_concern_flagged",
        inputs=EVASIVE_TRANSCRIPT,
        metadata={"expected_flag_metrics": ["management_tone_or_guidance_concern"]},
    ),
]

dataset = Dataset(
    name="transcripts",
    cases=_cases,
    evaluators=[
        TranscriptGroundingEvaluator(),
        ExpectedFlagsPresent(),
        UnavailableCaseCorrect(),
        LLMJudge(rubric=_SUMMARY_QUALITY_RUBRIC, model=TRANSCRIPT_ANALYST_MODEL),
    ],
)


if __name__ == "__main__":
    report = dataset.evaluate_sync(partial(run_transcript_analyst, "TEST"))
    report.print(include_input=False, include_output=True, include_durations=True)
