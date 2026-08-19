# Agents — Implementation Reference

For the agent roster's design intent (roles, I/O types, model tiers, capabilities), see `PRD.md`
§4 — that stays the source of truth for *intent*. This file is implementation-level detail once
an agent actually exists. Full design rationale for each agent also lives in its own
`.agents/plans/phase-N-*.md` file — this doc is the durable summary, the plan is the point-in-time
design record.

## Financial Statements Analyst (Phase 1)

**Module**: `src/agentic_fundamental_analyst/agents/financial_statements.py`
**Model**: `anthropic:claude-sonnet-5` (constant in `agents/models.py`, per the "model tier lives in
one shared place" convention). Bare model id confirmed present in pydantic-ai's
`AnthropicModelName`; the `anthropic:` prefix follows the standard `<provider>:<model>` convention
— not yet exercised against a real `.run()` call in this environment (see CLAUDE.md Current State).
**Capabilities**: none (single-shot, no tools) — matches the PRD roster exactly.

**Input**: `RatioTrendBundle`, not raw `FinancialStatementBundle` or `FiscalPeriod`. The agent
never sees unaggregated XBRL data — only deterministically-computed ratios (annual/10-K periods
only, oldest first), each either a real value or a `RatioResult(value=None, reason=...)`. This is
a deliberate narrowing beyond the PRD roster's literal "Input type: FinancialStatementBundle" —
see the Problem/Solution section of `.agents/plans/phase-1-financial-statements-analyst.md` for
why: it keeps the agent's job pure interpretation (no arithmetic it could get wrong) and keeps
grounding cheap to check.

**Output contract, and why it's split in two**:
- `FinancialAnalystAgentOutput` (the agent's actual `output_type`): `summary: str` +
  `flag_candidates: list[FlagCandidate]`. A `FlagCandidate` names a `(metric, fiscal_year,
  fiscal_period)` triple, a `Severity`, and a `description` — **it has no numeric `value` field**.
  The model is never trusted to restate a number as ground truth.
- `FinancialAnalystOutput` (what the pipeline stage actually returns): built by
  `run_financial_statements_analyst()` after a deterministic grounding pass. `_ground_candidates()`
  looks up the real `RatioResult.value` for each candidate's metric/period in the `RatioTrendBundle`
  and constructs the final `Flag.source: SourcedFigure` from code; any candidate whose metric/period
  doesn't resolve to a real value is dropped into `dropped_candidates` (a diagnostic list, not part
  of the memo) rather than silently kept or silently discarded.

This means grounding for `Flag.source.value` is true **by construction** — there is no failure
mode where the model states a flag against a number it invented, because the model never states
the number at all. The remaining gap this doesn't close is *prose* grounding (numbers appearing in
`summary`/`description` text) — see `evals.md` for how that's checked.

**Coverage gaps**: `FinancialAnalystOutput.coverage_gaps` is the union of `bundle.coverage_gaps`
(data-layer gaps, e.g. unresolved XBRL tag) and `_ratio_unavailable_gaps()` — a `CoverageGap` for
every `RatioResult` with `value is None` in the trend bundle (e.g. Beneish unavailable because
there's no prior period). Fully deterministic; the agent has no input into this list at all.

**Instructions**: see the `_INSTRUCTIONS` constant in the module. Key points worth knowing if
revising the prompt: (1) explicitly tells the model it has no filing text, so a capex spike can
only ever be a *candidate* flag, never resolved — that's the Investigator's job later; (2) states
the seven checklist thresholds as starting points for judgment, not mechanical triggers; (3)
explicitly permits raising zero flags, to counter the model's instinct to always find something.

**Deviation from the PRD's `SourcedFigure` sketch**: PRD §3 illustrates
`source: "EDGAR:CIK...:us-gaap:Revenues:CY2024Q4"` (XBRL-tag-level). This agent's `source` is
coarser: `"ratios.{metric}:{ticker}:{fiscal_year}{fiscal_period}"`, because `FiscalPeriod` (Phase 0)
doesn't retain which XBRL tag resolved each field. Flagged as an open item to revisit before the
memo's Appendix section (Phase 5) needs filing-level citations.

## Not yet built (Phase 2+)

Filings Analyst, Transcript Analyst, Flag Consolidator, Investigator, Sector Analyst, Macro
Sensitivity Analyst, Valuation Interpreter, Synthesizer (draft + resolve), Red-Team — see PRD §4
roster and §12 phase plan.
