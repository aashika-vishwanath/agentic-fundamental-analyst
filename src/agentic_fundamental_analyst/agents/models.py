"""Model tier per agent role — routing changes touch only this file (PRD §10).

'anthropic:claude-sonnet-5' — the bare model id 'claude-sonnet-5' is confirmed
present (non-deprecated) in pydantic-ai's AnthropicModelName; the 'anthropic:'
provider prefix follows pydantic-ai's standard <provider>:<model> convention.
Verify against a real agent.run_sync() call (see Level 4 manual validation)
before trusting this in a paid eval run.
"""

FINANCIAL_STATEMENTS_ANALYST_MODEL = "anthropic:claude-sonnet-5"
FILINGS_ANALYST_MODEL = "anthropic:claude-sonnet-5"
TRANSCRIPT_ANALYST_MODEL = "anthropic:claude-sonnet-5"
# Haiku tier (PRD §4 roster) — the Flag Consolidator's semantic-merge task is
# lower-judgment than either analyst, so it gets the cheapest tier.
FLAG_CONSOLIDATOR_MODEL = "anthropic:claude-haiku-4-5-20251001"
# Opus tier (PRD §4 roster) — the Investigator is the system's one agentic
# loop, doing open-ended judgment over web evidence, so it gets the most
# capable tier. Verified (.agents/plans/phase-3-investigator.md Research
# Findings §4) that claude-opus-5's profile has
# anthropic_supports_adaptive_thinking=True and
# anthropic_supports_forced_tool_choice=True, so Thinking(...) and a
# structured output_type coexist without pydantic-ai's extended-thinking /
# output-tool UserError — do not assume this holds for a different model
# without rechecking the profile (e.g. Haiku 4.5 does not support adaptive
# thinking at all).
INVESTIGATOR_MODEL = "anthropic:claude-opus-5"
