"""Configures Logfire once at import time, mirroring config.py's dotenv pattern.
Must stay safe to import with no LOGFIRE_TOKEN and no network — tests/unit
imports agent modules (for TestModel plumbing tests) under exactly those
conditions, and CI must stay zero-API-spend / key-free (CLAUDE.md Testing
Strategy). send_to_logfire="if-token-present" (a real logfire.configure()
literal — confirmed against logfire/_internal/config.py) sends data only when
a token is available (env var or local `logfire auth` credentials); otherwise
it configures a local, offline no-op tracer."""

import logfire

logfire.configure(send_to_logfire="if-token-present")
logfire.instrument_pydantic_ai()
