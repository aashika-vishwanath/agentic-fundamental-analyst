"""Test-session setup that must run before any test module is collected.

pydantic-ai's Agent(...) constructor eagerly validates that ANTHROPIC_API_KEY
is set when given an 'anthropic:...' model string — it constructs the provider
client at Agent-construction time, not at .run() time. Every agent module sets
up its Agent instance at import time (module-level), so merely importing
agents.financial_statements (which tests/unit/test_financial_statements_agent.py
must do, to override the agent with TestModel) would fail without a key.

This is a placeholder, never a real credential — no network call is ever made
with it, since every test overrides the model with TestModel/FunctionModel and
ALLOW_MODEL_REQUESTS below hard-fails any accidental real request regardless.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-not-a-real-key")

from pydantic_ai import models  # noqa: E402

models.ALLOW_MODEL_REQUESTS = False
