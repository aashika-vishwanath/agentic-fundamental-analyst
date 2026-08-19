"""The Transcript Analyst — interprets an opportunistically-found 8-K
transcript exhibit (~20-30% real-world coverage, PRD §7), or produces an
explicit coverage gap when none exists. See
.agents/plans/phase-2-filings-transcript-consolidator.md for full rationale,
including why this agent is never even called when no transcript is found
(a structural guarantee against fabricated commentary, stronger than
instructing the model to say "unavailable").
"""

import logfire
from pydantic_ai import Agent

from agentic_fundamental_analyst import config, observability  # noqa: F401
from agentic_fundamental_analyst.agents.grounding import quote_is_grounded
from agentic_fundamental_analyst.agents.models import TRANSCRIPT_ANALYST_MODEL
from agentic_fundamental_analyst.contracts.financials import CoverageGap
from agentic_fundamental_analyst.contracts.flags import Flag
from agentic_fundamental_analyst.contracts.sourcing import SourcedQuote
from agentic_fundamental_analyst.contracts.transcript_analyst import (
    TranscriptAnalystAgentOutput,
    TranscriptAnalystOutput,
    TranscriptFlagCandidate,
)
from agentic_fundamental_analyst.contracts.transcripts import TranscriptInput

_INSTRUCTIONS = """\
You are the Transcript Analyst for a fundamental-equity research system. You
receive the text of a real earnings-call transcript, opportunistically found
as an SEC 8-K exhibit. Every word in it is real; never invent commentary or
attribute a statement to a speaker who didn't make it.

Task:
1. Write a 2-4 sentence `summary` of what management actually said -- topics
   discussed, tone, any notable emphasis -- specific to this call, not
   generic earnings-call language.
2. Raise a flag candidate ONLY for `management_tone_or_guidance_concern`: a
   Q&A exchange where management gives a clearly hedged or evasive non-answer
   to a direct, specific analyst question about a number (revenue, margin,
   guidance), or walks back previously-stated guidance without explanation.
   This is a single, narrow, corroborating signal -- not a general sentiment
   score. An ordinary confident answer, even a cautious one with a stated
   reason, is not a flag.
3. Every flag candidate MUST carry `quoted_evidence`: the exact, verbatim
   text (copied character-for-character from the transcript, not
   paraphrased) that supports the flag. A quote that isn't a real, verbatim
   excerpt will be discarded.
4. Raising zero flags is a valid, expected outcome for a confident,
   straightforward call -- do not manufacture a flag to seem thorough.
"""

transcript_analyst = Agent(
    TRANSCRIPT_ANALYST_MODEL,
    name="transcript_analyst",
    output_type=TranscriptAnalystAgentOutput,
    instructions=_INSTRUCTIONS,
)


def _ground_transcript_candidates(
    transcript: TranscriptInput, candidates: list[TranscriptFlagCandidate]
) -> tuple[list[Flag], list[str]]:
    flags: list[Flag] = []
    dropped: list[str] = []
    for c in candidates:
        if not quote_is_grounded(c.quoted_evidence, transcript.text):
            dropped.append(f"{c.metric}: quote not verified verbatim")
            continue
        flags.append(
            Flag(
                metric=c.metric,
                fiscal_year=transcript.filed_date.year,
                fiscal_period="8K",
                severity=c.severity,
                description=c.description,
                source=SourcedQuote(
                    text=c.quoted_evidence,
                    source=f"EDGAR:{transcript.accession_number}:8K:{transcript.exhibit_document}",
                    as_of=transcript.filed_date,
                ),
            )
        )
    return flags, dropped


async def run_transcript_analyst(
    ticker: str, transcript: TranscriptInput | None
) -> TranscriptAnalystOutput:
    if transcript is None:
        # Structurally impossible to fabricate: the model is never invoked
        # at all, not merely instructed to say "unavailable."
        return TranscriptAnalystOutput(
            ticker=ticker,
            summary=None,
            flags=[],
            coverage_gaps=[
                CoverageGap(
                    field="transcript",
                    reason="no_transcript_exhibit_found_in_lookback_window",
                )
            ],
            dropped_candidates=[],
        )
    with logfire.span(
        "transcript_analyst_stage", ticker=ticker, accession_number=transcript.accession_number
    ) as span:
        result = await transcript_analyst.run(transcript.text)
        agent_output = result.output
        flags, dropped = _ground_transcript_candidates(transcript, agent_output.flag_candidates)
        span.set_attribute("flag_count", len(flags))
        span.set_attribute("dropped_candidate_count", len(dropped))
    return TranscriptAnalystOutput(
        ticker=ticker,
        summary=agent_output.summary,
        flags=flags,
        coverage_gaps=[],
        dropped_candidates=dropped,
    )
