import json

import pytest
from pydantic import ValidationError

from agentic_fundamental_analyst.contracts.memo import (
    RedTeamAgentOutput,
    SynthesizerDraftAgentOutput,
    SynthesizerResolveAgentOutput,
)

# Real quirk observed live (never seen against any eval dataset's small
# synthetic fixtures): Anthropic's tool-call output serialized a large,
# deeply nested list field as an escaped JSON string instead of a properly
# nested array. These tests exercise the model_validator(mode="before")
# coercion added to fix it, plus confirm a genuinely malformed string still
# raises a normal validation error rather than being silently swallowed.

_SECTION = {
    "title": "executive_summary_and_recommendation",
    "content": "Buy on strong fundamentals.",
    "cited_figures": [],
    "cited_quotes": [],
}


def test_synthesizer_draft_output_coerces_stringified_sections():
    raw = {"rating": "buy", "conviction": "high", "sections": json.dumps([_SECTION])}
    output = SynthesizerDraftAgentOutput.model_validate(raw)
    assert output.sections[0].title == "executive_summary_and_recommendation"


def test_synthesizer_draft_output_still_rejects_genuinely_invalid_string():
    raw = {"rating": "buy", "conviction": "high", "sections": "not valid json at all"}
    with pytest.raises(ValidationError):
        SynthesizerDraftAgentOutput.model_validate(raw)


def test_synthesizer_draft_output_accepts_native_list_unchanged():
    raw = {"rating": "buy", "conviction": "high", "sections": [_SECTION]}
    output = SynthesizerDraftAgentOutput.model_validate(raw)
    assert len(output.sections) == 1


def test_red_team_output_coerces_stringified_attack_candidates():
    candidate = {
        "section": "valuation",
        "category": "untraceable_claim",
        "quoted_claim": "a made-up number",
        "critique": "not grounded",
    }
    raw = {"attack_candidates": json.dumps([candidate])}
    output = RedTeamAgentOutput.model_validate(raw)
    assert output.attack_candidates[0].section == "valuation"


def test_synthesizer_resolve_output_coerces_both_stringified_lists():
    resolution = {
        "attack_index": 0,
        "resolution": "cut",
        "explanation": "no real basis",
    }
    raw = {
        "resolutions": json.dumps([resolution]),
        "rating": "hold",
        "conviction": "medium",
        "sections": json.dumps([_SECTION]),
    }
    output = SynthesizerResolveAgentOutput.model_validate(raw)
    assert output.resolutions[0].attack_index == 0
    assert output.sections[0].title == "executive_summary_and_recommendation"
