from datetime import date

from pydantic_ai.models.test import TestModel

from agentic_fundamental_analyst.agents.transcript import run_transcript_analyst, transcript_analyst
from agentic_fundamental_analyst.contracts.transcript_analyst import TranscriptAnalystAgentOutput
from agentic_fundamental_analyst.contracts.transcripts import TranscriptInput

TRANSCRIPT = TranscriptInput(
    accession_number="0001-24-000003",
    filed_date=date(2024, 5, 1),
    exhibit_document="ex991q124earningscalltrans.htm",
    text=(
        "Operator\nGood day and welcome to the call.\n"
        "Analyst\nCan you give us the exact gross margin number for the quarter?\n"
        "CFO\nWe're not going to get into that level of detail on this call, "
        "but we feel good about the trajectory."
    ),
)


def test_agent_default_test_model_produces_valid_output_type():
    with transcript_analyst.override(model=TestModel()):
        result = transcript_analyst.run_sync(TRANSCRIPT.text)
    assert isinstance(result.output, TranscriptAnalystAgentOutput)


async def test_run_transcript_analyst_none_input_short_circuits_without_calling_model():
    # No TestModel override is installed at all -- if the code tried to call
    # the real Anthropic model here, this would fail loudly (no real API key
    # is configured in tests/unit; see tests/conftest.py) rather than
    # silently succeed, proving the model truly isn't invoked.
    result = await run_transcript_analyst("TEST", None)

    assert result.summary is None
    assert result.flags == []
    assert len(result.coverage_gaps) == 1
    assert result.coverage_gaps[0].field == "transcript"
    assert result.coverage_gaps[0].reason == "no_transcript_exhibit_found_in_lookback_window"
    assert result.dropped_candidates == []


async def test_run_transcript_analyst_grounds_real_quote_and_drops_fabricated_one():
    scripted_output = {
        "summary": "Management declined to give an exact margin figure.",
        "flag_candidates": [
            {
                "metric": "management_tone_or_guidance_concern",
                "quoted_evidence": "We're not going to get into that level of detail on this call",
                "severity": "medium",
                "description": "Evasive on a direct margin question.",
            },
            {
                "metric": "management_tone_or_guidance_concern",
                "quoted_evidence": "we are lowering guidance due to weak demand",
                "severity": "high",
                "description": "Hallucinated -- not in the transcript.",
            },
        ],
    }
    with transcript_analyst.override(model=TestModel(custom_output_args=scripted_output)):
        result = await run_transcript_analyst("TEST", TRANSCRIPT)

    assert len(result.flags) == 1
    flag = result.flags[0]
    assert flag.metric == "management_tone_or_guidance_concern"
    assert flag.fiscal_year == 2024
    assert flag.fiscal_period == "8K"
    assert flag.source.as_of == date(2024, 5, 1)
    assert flag.source.source == "EDGAR:0001-24-000003:8K:ex991q124earningscalltrans.htm"

    assert len(result.dropped_candidates) == 1
