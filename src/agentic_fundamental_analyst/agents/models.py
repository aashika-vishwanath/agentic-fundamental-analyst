"""Model tier per agent role — routing changes touch only this file (PRD §10).

'anthropic:claude-sonnet-5' — the bare model id 'claude-sonnet-5' is confirmed
present (non-deprecated) in pydantic-ai's AnthropicModelName; the 'anthropic:'
provider prefix follows pydantic-ai's standard <provider>:<model> convention.
Verify against a real agent.run_sync() call (see Level 4 manual validation)
before trusting this in a paid eval run.
"""

FINANCIAL_STATEMENTS_ANALYST_MODEL = "anthropic:claude-sonnet-5"
