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
